"""Middleware that has to run before anything else."""

import secrets

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden

# With and without the trailing slash: CommonMiddleware normally adds it, and
# that runs after this.
HEALTH_CHECK_PATHS = frozenset(("/healthz", "/healthz/"))


class HealthCheckMiddleware:
    """Answers the load balancer before the Host header is validated.

    A load balancer health-checks a target by its address, so the request
    arrives with Host set to the instance's private IP. That address is not
    in ALLOWED_HOSTS and never can be -- it changes with every instance --
    so Django would answer 400, the target would read as unhealthy, and the
    environment would cycle instances forever while every setting looked
    correct.

    Returning here short-circuits before SecurityMiddleware, which is the
    same reason the HTTPS redirect never reaches this path.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # request.path does not validate the host; request.get_host() would.
        if request.path in HEALTH_CHECK_PATHS:
            return HttpResponse("OK", content_type="text/plain")

        return self.get_response(request)


# CloudFront adds this to every origin request. A viewer cannot remove it,
# and cannot forge it without the secret.
ORIGIN_HEADER = "HTTP_X_ORIGIN_VERIFY"


class CloudFrontOriginMiddleware:
    """Refuses requests that did not arrive through CloudFront.

    CloudFront terminates TLS, but the Elastic Beanstalk hostname stays
    reachable over plain HTTP, and anyone who learns it could use the whole
    site unencrypted -- which would make the certificate decorative. There
    is no certificate for *.elasticbeanstalk.com to redirect them to, so
    the origin refuses them instead.

    Ordered after HealthCheckMiddleware on purpose: the health check comes
    from the instance itself, never through CloudFront, and is answered
    before this runs.

    Does nothing when CLOUDFRONT_ORIGIN_SECRET is unset, so local work and
    the test suite are unaffected.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        secret = getattr(settings, "CLOUDFRONT_ORIGIN_SECRET", "")

        if secret:
            presented = request.META.get(ORIGIN_HEADER, "")
            # compare_digest rather than ==, so a wrong value can't be
            # narrowed down by timing the response.
            if not secrets.compare_digest(presented, secret):
                return HttpResponseForbidden(
                    "This site is served over HTTPS. Use the published address.",
                    content_type="text/plain",
                )

        return self.get_response(request)

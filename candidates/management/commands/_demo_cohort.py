"""Demo cohort data for `manage.py seed_demo`.

Six applicants for one role, spread across the pipeline, so the dashboard,
the stage tabs and the charts have something real to show. Each CV is written
to score differently against the same profile -- a pipeline where everybody
matches 100% teaches a viewer nothing about what the screening is for.

Data only. The seeding logic lives in seed_demo.py, and every record it
creates is tagged the same way, so `--clear` removes these too.

Leading underscore so Django's command discovery ignores this module.
"""

# Required: AWS, Docker, Kubernetes. Nice to have: Python, PostgreSQL.
# Deliberately different from the Backend Engineer profile, so the same
# candidate pool would score differently against each.
ROLE_TITLE = "Platform Engineer"
ROLE_REQUIRED = ("AWS", "Docker", "Kubernetes")
ROLE_NICE_TO_HAVE = ("Python", "PostgreSQL")

ROLE_DESCRIPTION = (
    "You'll own the infrastructure our product teams deploy onto: the clusters, "
    "the pipelines, and the paved road that makes shipping boring. We're a small "
    "team, so you'll be close to the services you support rather than handing "
    "tickets back and forth."
)


COHORT = [
    {
        "first_name": "Nadia",
        "last_name": "Haddad",
        "handle": "nadia.haddad",
        "phone": "07700 900201",
        "status": "Applied",
        "applied_days_ago": 2,
        "message": (
            "I've spent the last three years running Kubernetes in production and "
            "would like to do it somewhere the platform team isn't separate from "
            "the people using it."
        ),
        "cv": """Nadia Haddad
Platform Engineer

Experience
Platform Engineer, Northwind Retail (2023-2026)
Ran production workloads on AWS across three regions. Owned the Kubernetes
clusters end to end, including upgrades, autoscaling and the on-call rota.
Built the Docker base images every product team deploys from.
Wrote the deployment tooling in Python, replacing a pile of shell scripts.

Infrastructure Engineer, Calder Systems (2021-2023)
AWS estate management, Terraform modules, and container builds.

Skills
AWS, Kubernetes, Docker, Python, Terraform, Linux, CI/CD

Education
BEng Software Engineering, 2021""",
        "interviews": [],
    },
    {
        "first_name": "Daniel",
        "last_name": "Okoro",
        "handle": "daniel.okoro",
        "phone": "07700 900202",
        "status": "CV Screening",
        "applied_days_ago": 5,
        "message": "Strong AWS and Docker background, currently learning Kubernetes.",
        "cv": """Daniel Okoro
Cloud Engineer

Experience
Cloud Engineer, Harbourline (2022-2026)
Managed AWS accounts, networking and IAM for a fifty-person engineering
organisation. Packaged internal services with Docker and maintained the
build pipeline. Automated account provisioning in Python.

Support Engineer, Harbourline (2020-2022)
Second-line support for the platform, moving into infrastructure work.

Skills
AWS, Docker, Python, Bash, Terraform, monitoring and alerting

Education
BSc Information Systems, 2020""",
        "interviews": [],
    },
    {
        "first_name": "Ines",
        "last_name": "Duarte",
        "handle": "ines.duarte",
        "phone": "07700 900203",
        "status": "CV Screening Passed",
        "applied_days_ago": 9,
        "message": (
            "Happy to talk through the migration I led last year -- it's the piece "
            "of work I'd most want to be judged on."
        ),
        "cv": """Ines Duarte
Senior Platform Engineer

Experience
Senior Platform Engineer, Meridian Health (2021-2026)
Led the migration of a monolith onto Kubernetes on AWS without downtime.
Owned the Docker build and release process for twenty services.
Ran the PostgreSQL fleet: replication, backups, and the failover drills
nobody enjoys but everybody needs.

Systems Engineer, Vale Analytics (2018-2021)
Linux estate, storage, and the first container work at the company.

Skills
Kubernetes, AWS, Docker, PostgreSQL, Terraform, Prometheus, Go

Education
MSc Distributed Systems, 2018""",
        "interviews": [],
    },
    {
        "first_name": "Marcus",
        "last_name": "Webb",
        "handle": "marcus.webb",
        "phone": "07700 900204",
        "status": "HR Interview",
        "applied_days_ago": 16,
        "message": "Looking for a role with more ownership than my current one.",
        "cv": """Marcus Webb
Infrastructure Engineer

Experience
Infrastructure Engineer, Aldgate Media (2022-2026)
Ran AWS infrastructure for a content platform serving two million requests
a day. Managed Kubernetes clusters provisioned by another team, and owned
the PostgreSQL instances behind the publishing tools.

Junior Systems Administrator, Aldgate Media (2020-2022)

Skills
AWS, Kubernetes, PostgreSQL, Linux, Ansible, networking

Education
BSc Computer Networks, 2020""",
        "interviews": [
            {
                "type": "HR",
                "days_ago": 3,
                "status": "Completed",
                "role": "HR Interviewer",
                "rating": 4,
                "recommendation": "Pass",
                "comments": (
                    "Clear on why he wants to move and honest about what he hasn't "
                    "done -- said straight out that the clusters were provisioned "
                    "for him and he wants to own that next. Communicates well. "
                    "Worth a technical round to see how far the container gap goes."
                ),
                "reply": (
                    "Agreed. The missing Docker experience is the thing to probe, "
                    "not the Kubernetes exposure."
                ),
                "reply_role": "Technical Interviewer",
            }
        ],
    },
    {
        "first_name": "Aiko",
        "last_name": "Tanaka",
        "handle": "aiko.tanaka",
        "phone": "07700 900205",
        "status": "Technical Interview",
        "applied_days_ago": 21,
        "message": (
            "I've built the kind of platform you're describing twice now, and I'd "
            "like to do it a third time with the benefit of the mistakes."
        ),
        "cv": """Aiko Tanaka
Staff Platform Engineer

Experience
Staff Platform Engineer, Lumen Freight (2020-2026)
Designed and ran the container platform: Kubernetes on AWS, multi-region,
with Docker images built and signed in the pipeline. Wrote most of the
internal tooling in Python. Owned the PostgreSQL clusters and the runbooks
around them. Ran the incident review process.

Platform Engineer, Ostara Labs (2017-2020)
Early Kubernetes adoption, AWS migration, and developer tooling.

Skills
Kubernetes, AWS, Docker, Python, PostgreSQL, Terraform, observability

Education
BSc Computer Science, 2017""",
        "interviews": [
            {
                "type": "HR",
                "days_ago": 11,
                "status": "Completed",
                "role": "HR Interviewer",
                "rating": 5,
                "recommendation": "Pass",
                "comments": (
                    "Among the most straightforward conversations I've had this year. "
                    "Described a serious outage and what she got wrong in it without "
                    "being asked to. Strong fit for how this team works."
                ),
                "reply": None,
                "reply_role": None,
            },
            {
                "type": "Technical",
                "days_in": 2,
                "status": "Scheduled",
                "role": "Technical Interviewer",
                "rating": None,
                "recommendation": None,
                "comments": None,
                "reply": None,
                "reply_role": None,
            },
        ],
    },
    {
        "first_name": "Tobias",
        "last_name": "Lindqvist",
        "handle": "tobias.lindqvist",
        "phone": "07700 900206",
        "status": "Rejected",
        "applied_days_ago": 26,
        "message": "Keen to move from application work into platform engineering.",
        "cv": """Tobias Lindqvist
Backend Developer

Experience
Backend Developer, Fenwick Digital (2022-2026)
Built internal services in Python, backed by PostgreSQL. Took part in the
on-call rota and handled database migrations for the team.

Junior Developer, Fenwick Digital (2021-2022)

Skills
Python, PostgreSQL, SQL, REST APIs, Git

Education
BSc Software Engineering, 2021""",
        "interviews": [],
    },
]

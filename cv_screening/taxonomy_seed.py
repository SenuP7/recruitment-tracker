"""
Run with: python manage.py shell < cv_screening/taxonomy_seed.py
(or wrap this as a proper Django management command once it stabilises —
worth doing before QA, since management commands are repeatable/testable
whereas piping into shell isn't)

This is placeholder seed data. Replace with the real list once you've
built it with the BA (Master Plan, Card 2, build step 1).
"""

from cv_screening.models import Skill, Synonym

SEED = {
    "JavaScript": ["JS", "ECMAScript"],
    "Python": ["Python3", "Py"],
    "PostgreSQL": ["Postgres", "psql"],
    "Django": [],
    "React": ["ReactJS", "React.js"],
    "AWS": ["Amazon Web Services"],
    "Docker": ["containerisation", "containerization"],
    "REST API": ["RESTful API", "REST APIs", "API development"],
}

for skill_name, synonyms in SEED.items():
    skill, _ = Skill.objects.get_or_create(name=skill_name)
    for term in synonyms:
        Synonym.objects.get_or_create(term=term, defaults={"skill": skill})

print(f"Seeded {Skill.objects.count()} skills, {Synonym.objects.count()} synonyms.")

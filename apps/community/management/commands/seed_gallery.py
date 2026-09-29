import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.community.models import Comment
from apps.projects.models import Project
from apps.projects.templates import build_template

SEED_NAMESPACE = uuid.UUID('6f1c1b0e-6a51-4f7c-9a55-4d7f7b0f2c11')

SEEDS = [
    {'slug': 'seed-blink', 'template': 'blink', 'name': 'My First Blink', 'author': 'ada_maker', 'tags': ['beginner'], 'likes': 42, 'desc': 'The classic first circuit, cleaned up for sharing.'},
    {'slug': 'seed-traffic', 'template': 'traffic', 'name': 'Tiny Traffic Light', 'author': 'circuit_sam', 'tags': ['beginner', 'automotive'], 'likes': 31, 'desc': 'Three LEDs, one loop, zero stress.'},
    {'slug': 'seed-parking', 'template': 'parking', 'name': 'Garage Parking Sensor', 'author': 'hana_builds', 'tags': ['sensors', 'lcd'], 'likes': 88, 'desc': 'Ultrasonic sensor + LCD readout, buzzes when you get close.'},
    {'slug': 'seed-rgb', 'template': 'rgbled', 'name': 'RGB Mood Light', 'author': 'circuit_sam', 'tags': ['leds', 'pwm'], 'likes': 57, 'desc': 'Smooth PWM color cycling for a desk lamp.'},
    {'slug': 'seed-servoseg', 'template': 'servoseg', 'name': 'Servo Score Counter', 'author': 'ada_maker', 'tags': ['servo', 'display'], 'likes': 24, 'desc': 'A servo arm and a digit display counting together.'},
    {'slug': 'seed-relay', 'template': 'relaymotor', 'name': 'One-Button Fan Switch', 'author': 'hana_builds', 'tags': ['relay', 'motor'], 'likes': 19, 'desc': 'A button toggles a relay-driven motor.'},
]

# (seed slug, commenter, text, days ago)
SEED_COMMENTS = [
    ('seed-parking', 'nina_codes', 'Used this in my garage, works great!', 5),
    ('seed-parking', 'ada_maker', 'Nice use of the I2C LCD, saved me some pins.', 3),
    ('seed-rgb', 'hana_builds', 'Adding a potentiometer for manual control next.', 2),
]


def seed_id(slug):
    return uuid.uuid5(SEED_NAMESPACE, slug)


class Command(BaseCommand):
    help = 'Create (or refresh) the built-in community gallery circuits. Safe to run repeatedly.'

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        base = now - timedelta(days=12)
        for index, seed in enumerate(SEEDS):
            doc = build_template(seed['template'])
            when = base + timedelta(days=index)
            project, created = Project.objects.update_or_create(
                id=seed_id(seed['slug']),
                defaults={
                    'owner': None,
                    'author_name': seed['author'],
                    'name': seed['name'],
                    'description': seed['desc'],
                    'tags': seed['tags'],
                    'parts': doc['parts'],
                    'wires': doc['wires'],
                    'code': doc['code'],
                    'published': True,
                    'approved': True,
                    'is_seed': True,
                    'seed_likes': seed['likes'],
                },
            )
            if created:
                Project.objects.filter(pk=project.pk).update(created_at=when, published_at=when, approved_at=when)

        for slug, name, text, days_ago in SEED_COMMENTS:
            project_id = seed_id(slug)
            if Comment.objects.filter(project_id=project_id, user__isnull=True, name=name, text=text).exists():
                continue
            comment = Comment.objects.create(project_id=project_id, user=None, name=name, text=text)
            Comment.objects.filter(pk=comment.pk).update(created_at=now - timedelta(days=days_ago))

        self.stdout.write(self.style.SUCCESS(f'Gallery seeds ready ({len(SEEDS)} circuits).'))

import json
from datetime import timedelta

import pytest
from django.utils import timezone
from django.db import IntegrityError, transaction

from apps.community.models import Comment, Follow, Like
from apps.projects.models import Folder, Project
from apps.projects.services import clean_parts, create_starter_project
from apps.projects.templates import build_template

LIST = '/api/v1/projects/'


def detail(pk, suffix=''):
    return f'{LIST}{pk}/{suffix}'


class TestModels:
    def test_string_forms(self, user):
        assert str(Folder.objects.create(owner=user, name='Robots')) == 'Robots'
        assert str(Project.objects.create(owner=user, name='Blinker')) == 'Blinker'

    def test_author_property(self, user):
        assert Project.objects.create(owner=user, name='a').author == user.handle
        assert Project.objects.create(name='b', author_name='ada_maker').author == 'ada_maker'
        assert Project.objects.create(name='c').author == 'unknown'

    def test_manager_filters(self, user):
        public = Project.objects.create(owner=user, name='pub', published=True, approved=True)
        pending = Project.objects.create(owner=user, name='pend', published=True)
        Project.objects.create(owner=user, name='draft')
        seed = Project.objects.create(name='seed', is_seed=True, published=True)
        assert list(Project.objects.public()) == [public]
        assert list(Project.objects.pending()) == [pending]
        assert seed not in Project.objects.pending()

    def test_defaults(self, user):
        project = Project.objects.create(owner=user, name='d')
        assert project.tags == [] and project.parts == [] and project.wires == [] and project.code == ''
        assert project.published is False and project.approved is False and project.seed_likes == 0

    def test_deleting_a_user_cascades_everything_they_own(self, user, other_user):
        mine = Project.objects.create(owner=user, name='mine', published=True, approved=True)
        Folder.objects.create(owner=user, name='f')
        Like.objects.create(user=other_user, project=mine)
        Comment.objects.create(project=mine, user=other_user, name='Bob', text='hi')
        Follow.objects.create(follower=user, handle='someone')
        user.delete()
        assert not Project.objects.filter(pk=mine.pk).exists()
        assert Folder.objects.count() == 0
        assert Like.objects.count() == 0 and Comment.objects.count() == 0 and Follow.objects.count() == 0

    def test_like_and_follow_uniqueness_is_enforced_by_the_database(self, user):
        project = Project.objects.create(owner=user, name='p', published=True, approved=True)
        Like.objects.create(user=user, project=project)
        with pytest.raises(IntegrityError), transaction.atomic():
            Like.objects.create(user=user, project=project)
        Follow.objects.create(follower=user, handle='x')
        with pytest.raises(IntegrityError), transaction.atomic():
            Follow.objects.create(follower=user, handle='x')


class TestServices:
    def test_clean_parts_strips_only_transient_keys(self):
        parts = [{'id': 'a', 'pressed': True, 'triggered': False, 'props': {'pressed': 'keep-nested'}, 'x': 1}]
        assert clean_parts(parts) == [{'id': 'a', 'props': {'pressed': 'keep-nested'}, 'x': 1}]

    def test_clean_parts_does_not_mutate_the_input(self):
        original = [{'id': 'a', 'pressed': True}]
        clean_parts(original)
        assert original == [{'id': 'a', 'pressed': True}]

    def test_starter_project(self, user):
        starter = create_starter_project(user)
        template = build_template('parking')
        assert starter.owner == user and starter.name == 'My first circuit'
        assert starter.parts == template['parts'] and starter.code == template['code']
        assert starter.published is False


class TestTemplateIntegrity:
    @pytest.mark.parametrize('key', ['blank', 'blink', 'traffic', 'parking', 'rgbled', 'servoseg', 'relaymotor', 'sensors'])
    def test_wire_endpoints_reference_existing_parts_and_ids_are_unique(self, key):
        doc = build_template(key)
        ids = [p['id'] for p in doc['parts']]
        assert len(ids) == len(set(ids))
        wire_ids = [w['id'] for w in doc['wires']]
        assert len(wire_ids) == len(set(wire_ids))
        assert all(isinstance(p.get('x'), (int, float)) and isinstance(p.get('y'), (int, float)) for p in doc['parts'])

    def test_every_template_is_valid_json_serialisable(self):
        for key in ('blank', 'blink', 'parking'):
            json.dumps(build_template(key))

    def test_templates_have_arduino_code_structure(self):
        for key in ('blink', 'traffic', 'parking', 'rgbled', 'servoseg', 'relaymotor', 'sensors'):
            code = build_template(key)['code']
            assert 'void setup' in code and 'void loop' in code, key


class TestApiEdges:
    def test_project_list_is_newest_updated_first_and_autosave_bumps_it(self, auth_client, user):
        first = Project.objects.create(owner=user, name='first')
        second = Project.objects.create(owner=user, name='second')
        # explicit timestamps: coarse clocks (Windows) can tie back-to-back creates
        Project.objects.filter(pk=first.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        Project.objects.filter(pk=second.pk).update(updated_at=timezone.now())
        assert [p['name'] for p in auth_client.get(LIST).json()][0] == 'second'
        auth_client.patch(detail(first.pk), {'code': '// touched'}, format='json')
        assert [p['name'] for p in auth_client.get(LIST).json()][0] == 'first'

    def test_invalid_folder_id_formats(self, auth_client, user):
        project = Project.objects.create(owner=user, name='p')
        for bad in ('not-a-uuid', 123, [], {}):
            assert auth_client.patch(detail(project.pk), {'folder': bad}, format='json').status_code == 400

    def test_publish_twice_refreshes_the_submission_time(self, auth_client, user):
        project = Project.objects.create(owner=user, name='p')
        first = auth_client.post(detail(project.pk, 'publish/'), {}, format='json').json()['publishedAt']
        second = auth_client.post(detail(project.pk, 'publish/'), {}, format='json').json()['publishedAt']
        assert second >= first

    def test_publish_replaces_previous_description_and_tags(self, auth_client, user):
        project = Project.objects.create(owner=user, name='p', description='old', tags=['pwm'])
        body = auth_client.post(detail(project.pk, 'publish/'), {}, format='json').json()
        assert body['description'] == '' and body['tags'] == []

    def test_unpublish_when_never_published_is_harmless(self, auth_client, user):
        project = Project.objects.create(owner=user, name='p')
        assert auth_client.post(detail(project.pk, 'unpublish/')).status_code == 200

    def test_import_size_limits(self, auth_client):
        assert auth_client.post(LIST + 'import/', {'parts': [{'id': str(i)} for i in range(5001)]}, format='json').status_code == 400
        assert auth_client.post(LIST + 'import/', {'code': 'x' * 200_001}, format='json').status_code == 400
        assert auth_client.post(LIST + 'import/', {'name': 'n' * 121}, format='json').status_code == 400

    def test_import_ignores_client_supplied_ownership_and_flags(self, auth_client, user, other_user):
        response = auth_client.post(
            LIST + 'import/',
            {'name': 'x', 'owner': str(other_user.pk), 'ownerId': str(other_user.pk), 'published': True, 'approved': True},
            format='json',
        )
        body = response.json()
        assert body['ownerId'] == str(user.pk) and body['published'] is False and body['approved'] is False

    def test_create_ignores_client_supplied_ownership(self, auth_client, user, other_user):
        body = auth_client.post(LIST, {'owner': str(other_user.pk), 'ownerId': str(other_user.pk), 'seed': True}, format='json').json()
        assert body['ownerId'] == str(user.pk) and body['seed'] is False

    def test_folder_belongs_to_creator_even_if_owner_is_sent(self, auth_client, user, other_user):
        body = auth_client.post('/api/v1/folders/', {'name': 'f', 'owner': str(other_user.pk), 'ownerId': str(other_user.pk)}, format='json').json()
        assert body['ownerId'] == str(user.pk)

    def test_unicode_and_emoji_survive_a_round_trip(self, auth_client, user):
        project = Project.objects.create(owner=user, name='p')
        payload = {'name': '電子回路 \U0001F50C', 'code': '// café ☃', 'parts': [{'id': '☃'}]}
        auth_client.patch(detail(project.pk), payload, format='json')
        fetched = auth_client.get(detail(project.pk)).json()
        assert fetched['name'] == payload['name'] and fetched['code'] == payload['code'] and fetched['parts'] == payload['parts']

    def test_deeply_nested_parts_are_stored_verbatim(self, auth_client, user):
        project = Project.objects.create(owner=user, name='p')
        parts = [{'id': 'a', 'props': {'nested': {'list': [1, 2, {'deep': True}], 'none': None}}}]
        auth_client.patch(detail(project.pk), {'parts': parts}, format='json')
        assert auth_client.get(detail(project.pk)).json()['parts'] == parts

    def test_empty_body_patch_is_a_noop(self, auth_client, user):
        project = Project.objects.create(owner=user, name='keep', code='// keep')
        assert auth_client.patch(detail(project.pk), {}, format='json').status_code == 200
        project.refresh_from_db()
        assert project.name == 'keep' and project.code == '// keep'

    def test_whitespace_only_description_is_allowed_and_trimmed(self, auth_client, user):
        project = Project.objects.create(owner=user, name='p')
        assert auth_client.patch(detail(project.pk), {'description': '   '}, format='json').json()['description'] == ''

    def test_many_projects_list_in_bounded_queries(self, auth_client, user, django_assert_max_num_queries):
        Project.objects.bulk_create([Project(owner=user, name=f'p{i}') for i in range(25)])
        with django_assert_max_num_queries(4):
            assert len(auth_client.get(LIST).json()) == 25

    def test_gallery_list_has_no_n_plus_one(self, client, user, other_user, django_assert_max_num_queries):
        from django.utils import timezone

        for i in range(15):
            owner = user if i % 2 else other_user
            Project.objects.create(owner=owner, name=f'g{i}', published=True, approved=True, published_at=timezone.now())
        with django_assert_max_num_queries(4):
            assert len(client.get('/api/v1/gallery/').json()) == 15

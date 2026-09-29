import json
import uuid

import pytest

from apps.projects.models import Folder, Project
from apps.projects.templates import build_template, template_keys

LIST = '/api/v1/projects/'
FOLDERS = '/api/v1/folders/'


def detail(pk, suffix=''):
    return f'/api/v1/projects/{pk}/{suffix}'


@pytest.fixture
def project(user):
    return Project.objects.create(
        owner=user, name='Mine', parts=[{'id': 'a', 'type': 'led'}], wires=[{'id': 'w', 'a': 'a.A', 'b': 'a.K'}], code='// hi'
    )


# --------------------------------------------------------------- templates
class TestTemplates:
    def test_all_frontend_templates_are_available(self):
        assert set(template_keys()) == {
            'blank', 'blink', 'traffic', 'parking', 'rgbled', 'servoseg', 'relaymotor', 'sensors',
        }

    @pytest.mark.parametrize('key', ['blank', 'blink', 'traffic', 'parking', 'rgbled', 'servoseg', 'relaymotor', 'sensors'])
    def test_documents_are_well_formed(self, key):
        doc = build_template(key)
        assert set(doc) == {'parts', 'wires', 'code'}
        assert doc['parts'] and isinstance(doc['code'], str) and doc['code'].strip()
        part_ids = {p['id'] for p in doc['parts']}
        for wire in doc['wires']:
            for end in (wire['a'], wire['b']):
                owner = end.split('.')[0]
                assert owner in part_ids, (key, end)

    def test_build_returns_independent_copies(self):
        first = build_template('blink')
        first['parts'].clear()
        assert build_template('blink')['parts']

    def test_unknown_key(self):
        with pytest.raises(KeyError):
            build_template('nope')


# ------------------------------------------------------------------- CRUD
class TestProjectCrud:
    def test_requires_login(self, client, project):
        assert client.get(LIST).status_code == 401
        assert client.post(LIST, {}, format='json').status_code == 401
        assert client.get(detail(project.pk)).status_code == 401

    def test_create_defaults_to_blank_template(self, auth_client, user):
        response = auth_client.post(LIST, {}, format='json')
        assert response.status_code == 201
        body = response.json()
        assert body['name'] == 'Untitled circuit'
        assert body['ownerId'] == str(user.id)
        assert body['published'] is False and body['approved'] is False
        assert body['tags'] == [] and body['folder'] is None
        assert body['parts'] == build_template('blank')['parts']
        assert body['code'] == build_template('blank')['code']
        assert isinstance(body['createdAt'], int) and isinstance(body['updatedAt'], int)
        assert body['publishedAt'] is None

    def test_create_from_template(self, auth_client):
        response = auth_client.post(LIST, {'name': '  Blinky ', 'template': 'blink'}, format='json')
        assert response.status_code == 201
        body = response.json()
        assert body['name'] == 'Blinky'
        assert body['code'] == build_template('blink')['code']
        assert 'template' not in body

    def test_create_with_explicit_document_overrides_template(self, auth_client):
        response = auth_client.post(
            LIST, {'template': 'blink', 'parts': [{'id': 'x'}], 'wires': [], 'code': 'void setup(){}'}, format='json'
        )
        body = response.json()
        assert body['parts'] == [{'id': 'x'}]
        assert body['wires'] == []
        assert body['code'] == 'void setup(){}'

    def test_unknown_template(self, auth_client):
        response = auth_client.post(LIST, {'template': 'warp-drive'}, format='json')
        assert response.status_code == 400

    def test_blank_name_falls_back_to_default(self, auth_client):
        assert auth_client.post(LIST, {'name': '   '}, format='json').json()['name'] == 'Untitled circuit'

    def test_list_returns_only_my_projects_newest_first(self, auth_client, user, other_user):
        old = Project.objects.create(owner=user, name='old')
        Project.objects.create(owner=other_user, name='theirs')
        new = Project.objects.create(owner=user, name='new')
        names = [p['name'] for p in auth_client.get(LIST).json()]
        assert names == ['new', 'old']
        assert {old.name, new.name} == set(names)

    def test_retrieve(self, auth_client, project):
        body = auth_client.get(detail(project.pk)).json()
        assert body['id'] == str(project.pk)
        assert body['parts'] == project.parts
        assert body['author'] == project.owner.handle

    def test_other_users_projects_are_invisible(self, other_client, project):
        assert other_client.get(detail(project.pk)).status_code == 404
        assert other_client.patch(detail(project.pk), {'name': 'x'}, format='json').status_code == 404
        assert other_client.delete(detail(project.pk)).status_code == 404
        assert other_client.post(detail(project.pk, 'duplicate/')).status_code == 404
        assert other_client.post(detail(project.pk, 'publish/'), {}, format='json').status_code == 404
        assert other_client.get(detail(project.pk, 'export/')).status_code == 404
        project.refresh_from_db()
        assert project.name == 'Mine'

    def test_malformed_id_is_404(self, auth_client):
        assert auth_client.get('/api/v1/projects/seed-blink/').status_code == 404
        assert auth_client.get(detail(uuid.uuid4())).status_code == 404

    def test_patch_updates_only_sent_fields(self, auth_client, project):
        response = auth_client.patch(detail(project.pk), {'name': 'Renamed'}, format='json')
        assert response.status_code == 200
        project.refresh_from_db()
        assert project.name == 'Renamed'
        assert project.code == '// hi'

    def test_autosave_document(self, auth_client, project):
        payload = {
            'name': 'Saved',
            'parts': [{'id': 'p1', 'type': 'led', 'x': 1, 'y': 2, 'pressed': True, 'triggered': True}],
            'wires': [{'id': 'w1', 'a': 'p1.A', 'b': 'ard.5'}],
            'code': 'void loop() {}',
        }
        before = project.updated_at
        response = auth_client.patch(detail(project.pk), payload, format='json')
        assert response.status_code == 200
        project.refresh_from_db()
        assert project.parts == [{'id': 'p1', 'type': 'led', 'x': 1, 'y': 2}]  # transient state stripped
        assert project.wires == payload['wires']
        assert project.code == 'void loop() {}'
        assert project.updated_at > before

    def test_code_whitespace_is_preserved(self, auth_client, project):
        code = '  void setup() {\n\n}\n'
        auth_client.patch(detail(project.pk), {'code': code}, format='json')
        project.refresh_from_db()
        assert project.code == code

    def test_rename_to_blank_is_rejected(self, auth_client, project):
        assert auth_client.patch(detail(project.pk), {'name': ' '}, format='json').status_code == 400

    def test_cannot_set_owner_or_publication_flags(self, auth_client, project, other_user):
        auth_client.patch(
            detail(project.pk),
            {'published': True, 'approved': True, 'ownerId': str(other_user.pk), 'owner': str(other_user.pk), 'seed': True},
            format='json',
        )
        project.refresh_from_db()
        assert project.published is False and project.approved is False
        assert project.owner_id != other_user.pk and project.is_seed is False

    def test_template_cannot_be_applied_on_update(self, auth_client, project):
        assert auth_client.patch(detail(project.pk), {'template': 'blink'}, format='json').status_code == 400

    def test_put_is_not_allowed(self, auth_client, project):
        assert auth_client.put(detail(project.pk), {'name': 'x'}, format='json').status_code == 405

    def test_delete(self, auth_client, project):
        assert auth_client.delete(detail(project.pk)).status_code == 204
        assert not Project.objects.filter(pk=project.pk).exists()

    @pytest.mark.parametrize(
        'payload',
        [
            {'parts': 'nope'},
            {'parts': ['not-an-object']},
            {'wires': {'a': 1}},
            {'code': ['not', 'text']},
            {'name': 'x' * 121},
            {'description': 'x' * 2001},
            {'tags': 'beginner'},
        ],
    )
    def test_validation(self, auth_client, project, payload):
        assert auth_client.patch(detail(project.pk), payload, format='json').status_code == 400

    def test_size_limits(self, auth_client, project):
        too_many = [{'id': str(i)} for i in range(5001)]
        assert auth_client.patch(detail(project.pk), {'parts': too_many}, format='json').status_code == 400
        assert auth_client.patch(detail(project.pk), {'code': 'x' * 200_001}, format='json').status_code == 400


class TestTags:
    def test_normalised_and_deduplicated(self, auth_client, project):
        response = auth_client.patch(detail(project.pk), {'tags': [' LEDs ', 'leds', 'PWM', 'two words']}, format='json')
        assert response.status_code == 200
        assert response.json()['tags'] == ['leds', 'pwm', 'two words']

    @pytest.mark.parametrize('tags', [['bad"quote'], ['<script>'], [''], ['x' * 33], ['a'] * 1 + [f't{i}' for i in range(10)]])
    def test_rejects_unsafe_or_excessive_tags(self, auth_client, project, tags):
        assert auth_client.patch(detail(project.pk), {'tags': tags}, format='json').status_code == 400


# ---------------------------------------------------------------- folders
class TestFolders:
    def test_crud(self, auth_client, user):
        created = auth_client.post(FOLDERS, {'name': ' Robots '}, format='json')
        assert created.status_code == 201
        folder_id = created.json()['id']
        assert created.json()['name'] == 'Robots'
        assert [f['id'] for f in auth_client.get(FOLDERS).json()] == [folder_id]
        renamed = auth_client.patch(f'{FOLDERS}{folder_id}/', {'name': 'Bots'}, format='json')
        assert renamed.json()['name'] == 'Bots'
        assert auth_client.delete(f'{FOLDERS}{folder_id}/').status_code == 204
        assert not Folder.objects.exists()

    def test_blank_create_defaults_and_blank_rename_rejected(self, auth_client):
        folder = auth_client.post(FOLDERS, {'name': ''}, format='json').json()
        assert folder['name'] == 'New folder'
        assert auth_client.patch(f'{FOLDERS}{folder["id"]}/', {'name': ' '}, format='json').status_code == 400

    def test_isolated_between_users(self, auth_client, other_client, other_user):
        folder = Folder.objects.create(owner=other_user, name='private')
        assert auth_client.get(FOLDERS).json() == []
        assert auth_client.patch(f'{FOLDERS}{folder.pk}/', {'name': 'x'}, format='json').status_code == 404
        assert auth_client.delete(f'{FOLDERS}{folder.pk}/').status_code == 404

    def test_move_project_into_folder_and_out(self, auth_client, user, project):
        folder = Folder.objects.create(owner=user, name='f')
        moved = auth_client.patch(detail(project.pk), {'folder': str(folder.pk)}, format='json')
        assert moved.status_code == 200 and moved.json()['folder'] == str(folder.pk)
        cleared = auth_client.patch(detail(project.pk), {'folder': None}, format='json')
        assert cleared.json()['folder'] is None

    def test_cannot_move_into_someone_elses_folder(self, auth_client, other_user, project):
        foreign = Folder.objects.create(owner=other_user, name='theirs')
        response = auth_client.patch(detail(project.pk), {'folder': str(foreign.pk)}, format='json')
        assert response.status_code == 400
        project.refresh_from_db()
        assert project.folder is None

    def test_deleting_folder_keeps_projects(self, auth_client, user, project):
        folder = Folder.objects.create(owner=user, name='f')
        project.folder = folder
        project.save()
        auth_client.delete(f'{FOLDERS}{folder.pk}/')
        project.refresh_from_db()
        assert project.folder is None


# --------------------------------------------------------------- actions
class TestActions:
    def test_duplicate(self, auth_client, project, user):
        project.published = True
        project.approved = True
        project.description = 'public words'
        project.save()
        response = auth_client.post(detail(project.pk, 'duplicate/'))
        assert response.status_code == 201
        copy = response.json()
        assert copy['id'] != str(project.pk)
        assert copy['name'] == 'Copy of Mine'
        assert copy['published'] is False and copy['approved'] is False
        assert copy['parts'] == project.parts and copy['code'] == project.code
        assert Project.objects.filter(owner=user).count() == 2

    def test_duplicate_truncates_long_names(self, auth_client, user):
        long = Project.objects.create(owner=user, name='n' * 120)
        response = auth_client.post(detail(long.pk, 'duplicate/'))
        assert response.status_code == 201
        assert len(response.json()['name']) == 120

    def test_publish_submits_for_review(self, auth_client, project):
        response = auth_client.post(
            detail(project.pk, 'publish/'), {'description': 'Neat', 'tags': ['LEDs', 'beginner']}, format='json'
        )
        assert response.status_code == 200
        body = response.json()
        assert body['published'] is True and body['approved'] is False
        assert body['description'] == 'Neat' and body['tags'] == ['leds', 'beginner']
        assert isinstance(body['publishedAt'], int)
        assert auth_client.get('/api/v1/gallery/').json() == []  # not visible until approved

    def test_publish_with_no_body(self, auth_client, project):
        assert auth_client.post(detail(project.pk, 'publish/'), {}, format='json').status_code == 200

    def test_republishing_an_approved_circuit_requires_review_again(self, auth_client, project):
        project.published = True
        project.approved = True
        project.save()
        body = auth_client.post(detail(project.pk, 'publish/'), {}, format='json').json()
        assert body['approved'] is False
        assert body['approvedAt'] is None

    def test_publish_validates_input(self, auth_client, project):
        response = auth_client.post(detail(project.pk, 'publish/'), {'tags': ['bad"tag']}, format='json')
        assert response.status_code == 400
        project.refresh_from_db()
        assert project.published is False

    def test_unpublish(self, auth_client, project):
        project.published = True
        project.approved = True
        project.save()
        body = auth_client.post(detail(project.pk, 'unpublish/')).json()
        assert body['published'] is False and body['approved'] is False

    def test_export_and_import_round_trip(self, auth_client, project, user):
        exported = auth_client.get(detail(project.pk, 'export/'))
        assert exported.status_code == 200
        doc = exported.json()
        assert set(doc) == {'name', 'parts', 'wires', 'code'}
        imported = auth_client.post(LIST + 'import/', json.loads(json.dumps(doc)), format='json')
        assert imported.status_code == 201
        body = imported.json()
        assert body['name'] == 'Mine' and body['parts'] == project.parts and body['code'] == project.code
        assert body['id'] != str(project.pk)
        assert Project.objects.filter(owner=user).count() == 2

    def test_import_defaults_and_validation(self, auth_client):
        assert auth_client.post(LIST + 'import/', {}, format='json').json()['name'] == 'Imported circuit'
        assert auth_client.post(LIST + 'import/', {'parts': 'x'}, format='json').status_code == 400
        assert auth_client.post(LIST + 'import/', {'wires': [1]}, format='json').status_code == 400

    def test_import_strips_transient_part_state(self, auth_client):
        response = auth_client.post(LIST + 'import/', {'parts': [{'id': 'b', 'pressed': True}]}, format='json')
        assert response.json()['parts'] == [{'id': 'b'}]

    def test_import_requires_login(self, client):
        assert client.post(LIST + 'import/', {}, format='json').status_code == 401

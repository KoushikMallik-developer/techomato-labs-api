from datetime import timedelta
from unittest import mock

from django.db import IntegrityError
from django.utils import timezone

from apps.community.models import Comment, Follow, Like
from apps.projects.models import Project

GALLERY = '/api/v1/gallery/'


def make_public(owner, name='Public', when=None, **extra):
    when = when or timezone.now()
    data = dict(owner=owner, name=name, published=True, approved=True, published_at=when, approved_at=when, tags=['leds'])
    data.update(extra)
    return Project.objects.create(**data)


class TestRaces:
    def test_like_survives_a_concurrent_duplicate(self, auth_client, other_user):
        project = make_public(other_user)
        with mock.patch.object(Like.objects, 'get_or_create', side_effect=IntegrityError('duplicate')):
            response = auth_client.put(f'{GALLERY}{project.pk}/like/')
        assert response.status_code == 200 and response.json()['liked'] is True

    def test_follow_survives_a_concurrent_duplicate(self, auth_client):
        with mock.patch.object(Follow.objects, 'get_or_create', side_effect=IntegrityError('duplicate')):
            response = auth_client.put('/api/v1/following/somebody/')
        assert response.status_code == 200 and response.json()['following'] is True


class TestSorting:
    def test_popular_ties_break_by_newest(self, client, user):
        old = make_public(user, 'old', when=timezone.now() - timedelta(days=5))
        new = make_public(user, 'new', when=timezone.now())
        order = [i['id'] for i in client.get(GALLERY).json()]
        assert order == [str(new.pk), str(old.pk)]

    def test_likes_outrank_recency_in_popular(self, client, user, other_user):
        old_but_loved = make_public(user, 'loved', when=timezone.now() - timedelta(days=30))
        make_public(user, 'fresh')
        Like.objects.create(user=other_user, project=old_but_loved)
        assert client.get(GALLERY).json()[0]['name'] == 'loved'
        assert client.get(GALLERY, {'sort': 'new'}).json()[0]['name'] == 'fresh'

    def test_unknown_sort_falls_back_to_popular(self, client, user):
        make_public(user)
        assert client.get(GALLERY, {'sort': 'sideways'}).status_code == 200

    def test_seed_likes_count_toward_popularity(self, client, user, other_user):
        make_public(user, 'plain')
        make_public(other_user, 'boosted', seed_likes=50)
        body = client.get(GALLERY).json()
        assert body[0]['name'] == 'boosted' and body[0]['likeCount'] == 50


class TestFilters:
    def test_filters_combine(self, client, user, other_user):
        make_public(user, 'alice led', tags=['leds'])
        make_public(user, 'alice motor', tags=['motor'])
        make_public(other_user, 'bob led', tags=['leds'])
        found = client.get(GALLERY, {'author': user.handle, 'tag': 'leds'}).json()
        assert [i['name'] for i in found] == ['alice led']

    def test_search_is_case_insensitive_and_trims(self, client, user):
        make_public(user, 'Laser Cat')
        assert len(client.get(GALLERY, {'q': '  LASER  '}).json()) == 1

    def test_blank_filters_are_ignored(self, client, user):
        make_public(user)
        assert len(client.get(GALLERY, {'q': '', 'tag': '', 'author': ''}).json()) == 1

    def test_tag_filter_ignores_quotes_injection(self, client, user):
        make_public(user, tags=['leds'])
        assert client.get(GALLERY, {'tag': 'leds"]'}).json() == []
        assert client.get(GALLERY, {'tag': '"'}).json() == []

    def test_following_filter_with_nobody_followed(self, auth_client, user):
        make_public(user)
        assert auth_client.get(GALLERY, {'tag': '__following__'}).json() == []

    def test_following_filter_after_unfollow(self, auth_client, user, other_user):
        make_public(other_user)
        auth_client.put(f'/api/v1/following/{other_user.handle}/')
        assert len(auth_client.get(GALLERY, {'tag': '__following__'}).json()) == 1
        auth_client.delete(f'/api/v1/following/{other_user.handle}/')
        assert auth_client.get(GALLERY, {'tag': '__following__'}).json() == []


class TestVisibilityChanges:
    def test_unpublishing_hides_the_circuit_but_keeps_likes_and_comments(self, auth_client, other_client, user, other_user):
        project = make_public(user)
        other_client.put(f'{GALLERY}{project.pk}/like/')
        other_client.post(f'{GALLERY}{project.pk}/comments/', {'text': 'hi'}, format='json')
        auth_client.post(f'/api/v1/projects/{project.pk}/unpublish/')
        assert other_client.get(f'{GALLERY}{project.pk}/').status_code == 404
        assert other_client.get(f'{GALLERY}{project.pk}/comments/').status_code == 404
        assert Like.objects.filter(project=project).count() == 1 and Comment.objects.filter(project=project).count() == 1

    def test_republishing_and_reapproval_brings_likes_back(self, auth_client, admin_client, other_client, user):
        project = make_public(user)
        other_client.put(f'{GALLERY}{project.pk}/like/')
        auth_client.post(f'/api/v1/projects/{project.pk}/unpublish/')
        auth_client.post(f'/api/v1/projects/{project.pk}/publish/', {}, format='json')
        admin_client.post(f'/api/v1/admin/circuits/{project.pk}/approve/')
        assert other_client.get(f'{GALLERY}{project.pk}/').json()['likeCount'] == 1

    def test_deleting_the_project_removes_its_social_data(self, auth_client, other_client, user):
        project = make_public(user)
        other_client.put(f'{GALLERY}{project.pk}/like/')
        other_client.post(f'{GALLERY}{project.pk}/comments/', {'text': 'hi'}, format='json')
        auth_client.delete(f'/api/v1/projects/{project.pk}/')
        assert Like.objects.count() == 0 and Comment.objects.count() == 0

    def test_owner_can_like_and_comment_on_their_own_public_circuit(self, auth_client, user):
        project = make_public(user)
        assert auth_client.put(f'{GALLERY}{project.pk}/like/').status_code == 200
        assert auth_client.post(f'{GALLERY}{project.pk}/comments/', {'text': 'mine'}, format='json').status_code == 201


class TestCommentsEdges:
    def test_comment_shape_and_ordering(self, auth_client, other_client, user, other_user):
        project = make_public(user)
        for text in ('one', 'two', 'three'):
            other_client.post(f'{GALLERY}{project.pk}/comments/', {'text': text}, format='json')
        body = auth_client.get(f'{GALLERY}{project.pk}/comments/').json()
        assert [c['text'] for c in body] == ['one', 'two', 'three']
        assert set(body[0]) == {'id', 'userId', 'name', 'text', 'createdAt'}
        assert body[0]['userId'] == str(other_user.pk)

    def test_comment_name_is_a_snapshot_of_the_authors_name(self, auth_client, user, other_user):
        project = make_public(other_user)
        auth_client.post(f'{GALLERY}{project.pk}/comments/', {'text': 'hello'}, format='json')
        auth_client.patch('/api/v1/auth/me/', {'name': 'Brand New Name'}, format='json')
        assert auth_client.get(f'{GALLERY}{project.pk}/comments/').json()[0]['name'] == user.name

    def test_multiline_and_unicode_comments(self, auth_client, other_user):
        project = make_public(other_user)
        text = 'line one\nline two \U0001F44D café'
        created = auth_client.post(f'{GALLERY}{project.pk}/comments/', {'text': text}, format='json').json()
        assert created['text'] == text

    def test_comment_max_length_boundary(self, auth_client, other_user):
        project = make_public(other_user)
        assert auth_client.post(f'{GALLERY}{project.pk}/comments/', {'text': 'x' * 2000}, format='json').status_code == 201
        assert auth_client.post(f'{GALLERY}{project.pk}/comments/', {'text': 'x' * 2001}, format='json').status_code == 400

    def test_missing_text_field(self, auth_client, other_user):
        project = make_public(other_user)
        assert auth_client.post(f'{GALLERY}{project.pk}/comments/', {}, format='json').status_code == 400


class TestFollowsEdges:
    def test_follow_list_keeps_insertion_order(self, auth_client):
        for handle in ('zed', 'amy', 'mid'):
            auth_client.put(f'/api/v1/following/{handle}/')
        assert auth_client.get('/api/v1/following/').json() == ['zed', 'amy', 'mid']

    def test_unfollow_when_not_following_is_harmless(self, auth_client):
        assert auth_client.delete('/api/v1/following/nobody/').json() == {'handle': 'nobody', 'following': False}

    def test_handle_boundary_lengths(self, auth_client):
        assert auth_client.put('/api/v1/following/' + 'a' * 64 + '/').status_code == 200
        assert auth_client.put('/api/v1/following/' + 'a' * 65 + '/').status_code == 400

    def test_deleting_a_followed_account_does_not_break_the_follower(self, auth_client, user, other_user):
        auth_client.put(f'/api/v1/following/{other_user.handle}/')
        other_user.delete()
        assert auth_client.get('/api/v1/following/').json() == [other_user.handle]
        assert auth_client.get(GALLERY, {'tag': '__following__'}).json() == []


class TestRemixEdges:
    def test_remix_does_not_copy_publication_or_social_state(self, auth_client, user, other_user):
        source = make_public(other_user, 'src', description='public words', seed_likes=9)
        body = auth_client.post(f'{GALLERY}{source.pk}/remix/').json()
        assert body['published'] is False and body['approved'] is False
        assert body['description'] == '' and body['tags'] == [] and body['folder'] is None

    def test_remix_of_long_names_is_truncated_to_the_limit(self, auth_client, other_user):
        source = make_public(other_user, 'n' * 120)
        assert len(auth_client.post(f'{GALLERY}{source.pk}/remix/').json()['name']) == 120

    def test_remixes_are_independent_copies(self, auth_client, other_user):
        source = make_public(other_user, code='// original', parts=[{'id': 'a'}])
        copy_id = auth_client.post(f'{GALLERY}{source.pk}/remix/').json()['id']
        auth_client.patch(f'/api/v1/projects/{copy_id}/', {'code': '// changed', 'parts': []}, format='json')
        source.refresh_from_db()
        assert source.code == '// original' and source.parts == [{'id': 'a'}]

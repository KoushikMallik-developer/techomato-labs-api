from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.community.management.commands.seed_gallery import SEEDS, seed_id
from apps.community.models import Comment, Follow, Like
from apps.projects.models import Project

GALLERY = '/api/v1/gallery/'


def item_url(pk, suffix=''):
    return f'{GALLERY}{pk}/{suffix}'


def make_public(owner, name='Public one', **extra):
    now = timezone.now()
    defaults = dict(
        owner=owner, name=name, published=True, approved=True, published_at=now, approved_at=now,
        parts=[{'id': 'a'}], wires=[], code='// code', tags=['leds'],
    )
    defaults.update(extra)
    return Project.objects.create(**defaults)


@pytest.fixture
def seeded():
    call_command('seed_gallery', stdout=StringIO())


# -------------------------------------------------------------------- seeds
class TestSeedCommand:
    def test_creates_gallery_circuits_and_comments(self, seeded):
        assert Project.objects.filter(is_seed=True, published=True, approved=True).count() == len(SEEDS)
        assert Comment.objects.filter(user__isnull=True).count() == 3

    def test_is_idempotent(self, seeded):
        Like.objects.all().delete()
        call_command('seed_gallery', stdout=StringIO())
        call_command('seed_gallery', stdout=StringIO())
        assert Project.objects.filter(is_seed=True).count() == len(SEEDS)
        assert Comment.objects.count() == 3

    def test_ids_are_stable(self, seeded):
        assert Project.objects.filter(pk=seed_id('seed-parking')).exists()

    def test_rerun_restores_curated_fields_but_keeps_real_likes_and_comments(self, seeded, user, auth_client):
        pk = seed_id('seed-blink')
        auth_client.put(item_url(pk, 'like/'))
        auth_client.post(item_url(pk, 'comments/'), {'text': 'hi'}, format='json')
        Project.objects.filter(pk=pk).update(name='vandalised')
        call_command('seed_gallery', stdout=StringIO())
        assert Project.objects.get(pk=pk).name == 'My First Blink'
        assert Like.objects.filter(project_id=pk).count() == 1
        assert Comment.objects.filter(project_id=pk, user=user).count() == 1

    def test_seeds_have_valid_circuits(self, seeded):
        for project in Project.objects.filter(is_seed=True):
            assert project.parts and project.code


# -------------------------------------------------------------------- list
class TestGalleryList:
    def test_public_and_shows_seeds(self, client, seeded):
        response = client.get(GALLERY)
        assert response.status_code == 200
        items = response.json()
        assert len(items) == len(SEEDS)
        first = items[0]
        assert {'id', 'author', 'name', 'description', 'tags', 'parts', 'wires', 'code', 'likeCount', 'liked', 'seed', 'publishedAt'} <= set(first)
        assert first['liked'] is False

    def test_popular_sort_is_default(self, client, seeded):
        counts = [i['likeCount'] for i in client.get(GALLERY).json()]
        assert counts == sorted(counts, reverse=True)
        assert counts[0] == 88

    def test_new_sort(self, client, seeded, user):
        newest = make_public(user, 'Brand new')
        assert client.get(GALLERY, {'sort': 'new'}).json()[0]['id'] == str(newest.pk)

    def test_only_approved_circuits_are_listed(self, client, user):
        make_public(user, 'visible')
        make_public(user, 'not approved', approved=False)
        make_public(user, 'not published', published=False, approved=False)
        Project.objects.create(owner=user, name='private')
        assert [i['name'] for i in client.get(GALLERY).json()] == ['visible']

    def test_author_is_the_owner_handle(self, client, user):
        make_public(user)
        assert client.get(GALLERY).json()[0]['author'] == user.handle

    def test_search_matches_name_description_and_tags(self, client, user):
        make_public(user, 'Laser Cat Toy', description='pew', tags=['motor'])
        make_public(user, 'Other', description='very Sparkly indeed', tags=['servo'])
        make_public(user, 'Third', description='', tags=['sensors'])
        names = lambda q: sorted(i['name'] for i in client.get(GALLERY, {'q': q}).json())  # noqa: E731
        assert names('laser') == ['Laser Cat Toy']
        assert names('SPARKLY') == ['Other']
        assert names('sens') == ['Third']
        assert names('zzz') == []

    def test_search_treats_wildcards_literally(self, client, user):
        make_public(user, 'plain')
        assert client.get(GALLERY, {'q': '%'}).json() == []
        assert client.get(GALLERY, {'q': '_'}).json() == []

    def test_tag_filter_is_exact(self, client, user):
        make_public(user, 'a', tags=['led'])
        make_public(user, 'b', tags=['leds'])
        make_public(user, 'c', tags=['leds', 'pwm'])
        assert sorted(i['name'] for i in client.get(GALLERY, {'tag': 'leds'}).json()) == ['b', 'c']
        assert sorted(i['name'] for i in client.get(GALLERY, {'tag': 'led'}).json()) == ['a']
        assert client.get(GALLERY, {'tag': 'le'}).json() == []
        assert [i['name'] for i in client.get(GALLERY, {'tag': 'LEDS', 'q': 'b'}).json()] == ['b']

    def test_author_filter(self, client, user, other_user, seeded):
        make_public(user, 'alice one')
        make_public(other_user, 'bob one')
        assert [i['name'] for i in client.get(GALLERY, {'author': user.handle}).json()] == ['alice one']
        assert len(client.get(GALLERY, {'author': 'ada_maker'}).json()) == 2

    def test_following_filter(self, auth_client, client, user, other_user, seeded):
        make_public(other_user, 'bob one')
        make_public(user, 'my own')
        Follow.objects.create(follower=user, handle=other_user.handle)
        Follow.objects.create(follower=user, handle='hana_builds')
        names = sorted(i['name'] for i in auth_client.get(GALLERY, {'tag': '__following__'}).json())
        assert names == ['Garage Parking Sensor', 'One-Button Fan Switch', 'bob one']
        assert client.get(GALLERY, {'tag': '__following__'}).json() == []

    def test_liked_flag_and_counts(self, auth_client, client, user, other_user):
        mine = make_public(user, 'liked by me')
        theirs = make_public(other_user, 'not liked')
        Like.objects.create(user=user, project=mine)
        Like.objects.create(user=other_user, project=mine)
        as_user = {i['name']: i for i in auth_client.get(GALLERY).json()}
        assert as_user['liked by me']['liked'] is True and as_user['liked by me']['likeCount'] == 2
        assert as_user['not liked']['liked'] is False and as_user['not liked']['likeCount'] == 0
        anon = {i['name']: i for i in client.get(GALLERY).json()}
        assert anon['liked by me']['liked'] is False and anon['liked by me']['likeCount'] == 2
        assert theirs.pk

    def test_likes_add_to_seed_likes(self, auth_client, seeded):
        pk = seed_id('seed-blink')
        auth_client.put(item_url(pk, 'like/'))
        item = auth_client.get(item_url(pk)).json()
        assert item['likeCount'] == 43 and item['liked'] is True


class TestGalleryDetail:
    def test_public_detail(self, client, user):
        project = make_public(user)
        response = client.get(item_url(project.pk))
        assert response.status_code == 200
        body = response.json()
        assert body['id'] == str(project.pk)
        assert body['parts'] == [{'id': 'a'}] and body['code'] == '// code'
        assert body['ownerId'] == str(user.pk)

    @pytest.mark.parametrize('flags', [dict(approved=False), dict(published=False, approved=False)])
    def test_unapproved_is_404_even_for_the_owner(self, auth_client, user, flags):
        project = make_public(user, **flags)
        assert auth_client.get(item_url(project.pk)).status_code == 404

    def test_unknown_id(self, client):
        assert client.get(item_url('00000000-0000-0000-0000-000000000000')).status_code == 404

    def test_seed_detail(self, client, seeded):
        body = client.get(item_url(seed_id('seed-parking'))).json()
        assert body['seed'] is True and body['author'] == 'hana_builds' and body['ownerId'] is None


# -------------------------------------------------------------------- likes
class TestLikes:
    def test_like_and_unlike_are_idempotent(self, auth_client, user, other_user):
        project = make_public(other_user)
        for _ in range(2):
            body = auth_client.put(item_url(project.pk, 'like/')).json()
            assert body == {'liked': True, 'likeCount': 1}
        assert Like.objects.count() == 1
        for _ in range(2):
            assert auth_client.delete(item_url(project.pk, 'like/')).json() == {'liked': False, 'likeCount': 0}

    def test_requires_login(self, client, user):
        project = make_public(user)
        assert client.put(item_url(project.pk, 'like/')).status_code == 401
        assert client.delete(item_url(project.pk, 'like/')).status_code == 401

    def test_cannot_like_hidden_circuit(self, auth_client, other_user):
        project = make_public(other_user, approved=False)
        assert auth_client.put(item_url(project.pk, 'like/')).status_code == 404

    def test_deleting_account_removes_likes(self, auth_client, other_user):
        project = make_public(other_user)
        auth_client.put(item_url(project.pk, 'like/'))
        auth_client.delete('/api/v1/auth/me/')
        assert Like.objects.count() == 0


# ----------------------------------------------------------------- comments
class TestComments:
    def test_list_is_public_and_chronological(self, client, user, seeded):
        pk = seed_id('seed-parking')
        Comment.objects.create(project_id=pk, user=user, name=user.name, text='newest')
        texts = [c['text'] for c in client.get(item_url(pk, 'comments/')).json()]
        assert texts == [
            'Used this in my garage, works great!',
            'Nice use of the I2C LCD, saved me some pins.',
            'newest',
        ]

    def test_add(self, auth_client, user, other_user):
        project = make_public(other_user)
        response = auth_client.post(item_url(project.pk, 'comments/'), {'text': '  Nice build! '}, format='json')
        assert response.status_code == 201
        body = response.json()
        assert body['text'] == 'Nice build!' and body['name'] == user.name and body['userId'] == str(user.pk)
        assert isinstance(body['createdAt'], int)
        assert len(auth_client.get(item_url(project.pk, 'comments/')).json()) == 1

    @pytest.mark.parametrize('text', ['', '   ', None, 'x' * 2001])
    def test_rejects_empty_or_huge(self, auth_client, other_user, text):
        project = make_public(other_user)
        assert auth_client.post(item_url(project.pk, 'comments/'), {'text': text}, format='json').status_code == 400
        assert Comment.objects.count() == 0

    def test_requires_login_to_post(self, client, user):
        project = make_public(user)
        assert client.post(item_url(project.pk, 'comments/'), {'text': 'hi'}, format='json').status_code == 401

    def test_hidden_circuit_has_no_comments_endpoint(self, auth_client, other_user):
        project = make_public(other_user, approved=False)
        assert auth_client.get(item_url(project.pk, 'comments/')).status_code == 404
        assert auth_client.post(item_url(project.pk, 'comments/'), {'text': 'hi'}, format='json').status_code == 404

    def test_delete_own_only(self, auth_client, other_client, user, other_user):
        project = make_public(other_user)
        comment = Comment.objects.create(project=project, user=user, name=user.name, text='mine')
        assert other_client.delete(item_url(project.pk, f'comments/{comment.pk}/')).status_code == 404
        assert Comment.objects.filter(pk=comment.pk).exists()
        assert auth_client.delete(item_url(project.pk, f'comments/{comment.pk}/')).status_code == 204
        assert not Comment.objects.filter(pk=comment.pk).exists()

    def test_delete_scoped_to_the_right_project(self, auth_client, user, other_user):
        one = make_public(other_user, 'one')
        two = make_public(other_user, 'two')
        comment = Comment.objects.create(project=one, user=user, name=user.name, text='mine')
        assert auth_client.delete(item_url(two.pk, f'comments/{comment.pk}/')).status_code == 404
        assert Comment.objects.filter(pk=comment.pk).exists()

    def test_seed_comments_cannot_be_deleted(self, auth_client, seeded):
        comment = Comment.objects.filter(user__isnull=True).first()
        response = auth_client.delete(item_url(comment.project_id, f'comments/{comment.pk}/'))
        assert response.status_code == 404

    def test_comments_survive_author_account_deletion(self, auth_client, other_user):
        project = make_public(other_user)
        auth_client.post(item_url(project.pk, 'comments/'), {'text': 'still here'}, format='json')
        auth_client.delete('/api/v1/auth/me/')
        comment = Comment.objects.get()
        assert comment.user is None and comment.text == 'still here'


# -------------------------------------------------------------------- remix
class TestRemix:
    def test_copies_into_my_projects(self, auth_client, user, other_user):
        source = make_public(other_user, 'Cool circuit', code='// original')
        response = auth_client.post(item_url(source.pk, 'remix/'))
        assert response.status_code == 201
        body = response.json()
        assert body['name'] == 'Cool circuit (remix)'
        assert body['ownerId'] == str(user.pk)
        assert body['code'] == '// original' and body['published'] is False
        source.refresh_from_db()
        assert source.owner_id == other_user.pk

    def test_works_for_seeds(self, auth_client, seeded):
        assert auth_client.post(item_url(seed_id('seed-blink'), 'remix/')).status_code == 201

    def test_requires_login_and_public_source(self, client, auth_client, other_user):
        public = make_public(other_user)
        hidden = make_public(other_user, 'hidden', approved=False)
        assert client.post(item_url(public.pk, 'remix/')).status_code == 401
        assert auth_client.post(item_url(hidden.pk, 'remix/')).status_code == 404


# ------------------------------------------------------------------ follows
class TestFollows:
    FOLLOWING = '/api/v1/following/'

    def test_follow_unfollow_and_list(self, auth_client, user):
        assert auth_client.get(self.FOLLOWING).json() == []
        for _ in range(2):
            assert auth_client.put(f'{self.FOLLOWING}hana_builds/').json() == {'handle': 'hana_builds', 'following': True}
        assert auth_client.get(self.FOLLOWING).json() == ['hana_builds']
        assert Follow.objects.count() == 1
        for _ in range(2):
            assert auth_client.delete(f'{self.FOLLOWING}hana_builds/').json()['following'] is False
        assert auth_client.get(self.FOLLOWING).json() == []

    def test_follows_are_per_user(self, auth_client, other_client):
        auth_client.put(f'{self.FOLLOWING}ada_maker/')
        assert other_client.get(self.FOLLOWING).json() == []

    def test_requires_login(self, client):
        assert client.get(self.FOLLOWING).status_code == 401
        assert client.put(f'{self.FOLLOWING}ada_maker/').status_code == 401

    def test_cannot_follow_yourself(self, auth_client, user):
        assert auth_client.put(f'{self.FOLLOWING}{user.handle}/').status_code == 400

    @pytest.mark.parametrize('handle', ['bad handle', 'a' * 65, 'semi;colon', 'dot.dot'])
    def test_rejects_malformed_handles(self, auth_client, handle):
        assert auth_client.put(f'{self.FOLLOWING}{handle}/').status_code in (400, 404)
        assert Follow.objects.count() == 0

    def test_can_follow_real_users_by_handle(self, auth_client, other_user):
        assert auth_client.put(f'{self.FOLLOWING}{other_user.handle}/').status_code == 200


def test_old_projects_do_not_leak_into_gallery_after_owner_unpublishes(client, user):
    project = make_public(user)
    Project.objects.filter(pk=project.pk).update(published=False, approved=False, published_at=timezone.now() - timedelta(days=1))
    assert client.get(GALLERY).json() == []


@pytest.mark.parametrize('param', ['q', 'tag', 'author'])
def test_nul_characters_in_query_params_do_not_crash(client, user, param):
    make_public(user, 'visible')
    response = client.get(GALLERY, {param: 'x' + chr(0)})
    assert response.status_code == 200
    # the NUL is dropped, leaving a normal (here: non-matching) filter
    assert client.get(GALLERY, {param: chr(0)}).status_code == 200

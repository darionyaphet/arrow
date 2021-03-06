# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import json
from unittest.mock import Mock

import click
import pytest
import responses as rsps

from archery.bot import CommentBot, CommandError, group


@pytest.fixture
def responses():
    with rsps.RequestsMock() as mock:
        yield mock


def github_url(path):
    return 'https://api.github.com:443/{}'.format(path.strip('/'))


@group()
def custom_handler():
    pass


@custom_handler.command()
@click.pass_obj
def extra(obj):
    return obj


@custom_handler.command()
@click.option('--force', '-f', is_flag=True)
def build(force):
    return force


@custom_handler.command()
@click.option('--name', required=True)
def benchmark(name):
    return name


def test_click_based_commands():
    assert custom_handler('build') is False
    assert custom_handler('build -f') is True

    assert custom_handler('benchmark --name strings') == 'strings'
    with pytest.raises(CommandError):
        assert custom_handler('benchmark')

    assert custom_handler('extra', extra='data') == {'extra': 'data'}


@pytest.mark.parametrize('fixture_name', [
    # the bot is not mentioned, nothing to do
    'event-issue-comment-not-mentioning-ursabot.json',
    # don't respond to itself, it prevents recursive comment storms!
    'event-issue-comment-by-ursabot.json',
    # non-authorized user sent the comment, do not respond
    'event-issue-comment-by-non-authorized-user.json',
])
def test_noop_events(load_fixture, fixture_name):
    payload = load_fixture(fixture_name)

    handler = Mock()
    bot = CommentBot(name='ursabot', token='', handler=handler)
    bot.handle('issue_comment', payload)

    handler.assert_not_called()


def test_issue_comment_without_pull_request(load_fixture, responses):
    responses.add(
        responses.GET,
        github_url('/repositories/169101701/issues/19'),
        json=load_fixture('issue-19.json'),
        status=200
    )
    responses.add(
        responses.GET,
        github_url('repos/ursa-labs/ursabot/pulls/19'),
        json={},
        status=404
    )
    responses.add(
        responses.POST,
        github_url('/repos/ursa-labs/ursabot/issues/19/comments'),
        json={}
    )

    def handler(command, **kwargs):
        pass

    payload = load_fixture('event-issue-comment-without-pull-request.json')
    bot = CommentBot(name='ursabot', token='', handler=handler)
    bot.handle('issue_comment', payload)

    post = responses.calls[2]
    assert json.loads(post.request.body) == {
        'body': "The comment bot only listens to pull request comments!"
    }


def test_respond_with_usage(load_fixture, responses):
    responses.add(
        responses.GET,
        github_url('/repositories/169101701/issues/26'),
        json=load_fixture('issue-26.json'),
        status=200
    )
    responses.add(
        responses.GET,
        github_url('/repos/ursa-labs/ursabot/pulls/26'),
        json=load_fixture('pull-request-26.json'),
        status=200
    )
    responses.add(
        responses.GET,
        github_url('/repos/ursa-labs/ursabot/issues/comments/480243811'),
        json=load_fixture('issue-comment-480243811.json')
    )
    responses.add(
        responses.POST,
        github_url('/repos/ursa-labs/ursabot/issues/26/comments'),
        json={}
    )

    def handler(command, **kwargs):
        raise CommandError('test-usage')

    payload = load_fixture('event-issue-comment-with-empty-command.json')
    bot = CommentBot(name='ursabot', token='', handler=handler)
    bot.handle('issue_comment', payload)

    post = responses.calls[3]
    assert json.loads(post.request.body) == {'body': '```\ntest-usage\n```'}


@pytest.mark.parametrize(('command', 'reaction'), [
    ('@ursabot build', '+1'),
    ('@ursabot build\nwith a comment', '+1'),
    ('@ursabot listen', '-1'),
])
def test_issue_comment_with_commands(load_fixture, responses, command,
                                     reaction):
    responses.add(
        responses.GET,
        github_url('/repositories/169101701/issues/26'),
        json=load_fixture('issue-26.json'),
        status=200
    )
    responses.add(
        responses.GET,
        github_url('/repos/ursa-labs/ursabot/pulls/26'),
        json=load_fixture('pull-request-26.json'),
        status=200
    )
    responses.add(
        responses.GET,
        github_url('/repos/ursa-labs/ursabot/issues/comments/480248726'),
        json=load_fixture('issue-comment-480248726.json')
    )
    responses.add(
        responses.POST,
        github_url(
            '/repos/ursa-labs/ursabot/issues/comments/480248726/reactions'
        ),
        json={}
    )

    def handler(command, **kwargs):
        if command == 'build':
            return True
        else:
            raise ValueError('Only `build` command is supported.')

    payload = load_fixture('event-issue-comment-build-command.json')
    payload["comment"]["body"] = command

    bot = CommentBot(name='ursabot', token='', handler=handler)
    bot.handle('issue_comment', payload)

    post = responses.calls[3]
    assert json.loads(post.request.body) == {'content': reaction}


def test_issue_comment_with_commands_bot_not_first(load_fixture, responses):
    # when the @-mention is not first, this is a no-op
    handler = Mock()

    payload = load_fixture('event-issue-comment-build-command.json')
    payload["comment"]["body"] = 'with a comment\n@ursabot build'

    bot = CommentBot(name='ursabot', token='', handler=handler)
    bot.handle('issue_comment', payload)

    handler.assert_not_called()

import asyncio
import datetime
import html.parser
import textwrap
import os
import re

import aiohttp
import feedparser
import paramiko
from aiohttp import web
from gidgethub import routing, sansio
from gidgethub import aiohttp as gh_aiohttp


PYDATA_WEBSERVER_IP = "104.130.226.93"
PYDATA_WEBSERVER_USERNAME = "asv-watcher"
GH_ORG_WHITELIST = {
    # "pandas-dev"
}

xpr = re.compile(
    r"<a href=\".*?\">(?P<PERCENT>.*?%) regression</a> on .*? "
    "in commits? <a href=\"https://github.com/"
    "(?P<GH_ORG>.+)/(?P<GH_REPO>.+)/commit/(?P<SHA>[\w\d]+)"
)
router = routing.Router()


@router.register("issues", action="opened")
async def issued_open_event(event, gh, *args, **kwargs):
    url = event.data["issue"]["comments_url"]
    author = event.data["issue"]["user"]["login"]

    message = f"Thanks for the report @{author}! I will look into it ASAP! (I'm a bot)."
    await gh.post(url, data={"body": message})


@router.register("push")
async def on_commit(event, gh, *args, **kwargs):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.client.AutoAddPolicy)
    password = os.environ['PYDATA_WEBSERVER_PASSWORD']
    client.connect(PYDATA_WEBSERVER_IP,
                   username=PYDATA_WEBSERVER_USERNAME,
                   password=password)

    command = (
        'git -C /usr/share/nginx/asv-collection/ fetch origin '
        '&& git -C /usr/share/nginx/asv-collection/ reset --hard origin/master'
    )
    stdin, stdout, stderr = client.exec_command(command)
    print(stdout.read().decode())


async def main(request):
    body = await request.read()

    secret = os.environ['GH_SECRET']
    oauth_token = os.environ['GH_AUTH']
    event = sansio.Event.from_http(
        request.headers,
        body,
        secret=secret
    )

    async with aiohttp.ClientSession() as session:
        gh = gh_aiohttp.GitHubAPI(session, "asv-bot", oauth_token=oauth_token)
        await router.dispatch(event, gh)
        response = await session.get("https://pandas.pydata.org/speed")
        text = await response.text()
        parser = ProjectParser()
        parser.feed(text)
        projects = parser.projects
        # today = datetime.date.today()
        today = datetime.date(2019, 4, 5)
        futures = [
            handle_regressions(project, gh, since=today)
            for project in projects
        ]
        await asyncio.gather(*futures)

    return web.Response(status=200)


# ----------------------------------------------------------------------------
# RSS stuff


class ProjectParser(html.parser.HTMLParser):

    def __init__(self, *, convert_charrefs=True):
        self.projects = []
        super().__init__(convert_charrefs=convert_charrefs)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            print(tag, attrs)
            self.projects.append(attrs[0][1])


async def handle_regressions(project, gh: gh_aiohttp.GitHubAPI, since: datetime.date):
    print(f"Checking for regressions for {project} since {since}")
    # TODO: nonblocking feedparser
    url = f"http://pandas.pydata.org/speed/{project}/regressions.xml"
    feed = feedparser.parse(url)
    entries = feed['entries']

    keep = []

    for entry in entries:
        # TODO: Find how to only *fetch* new entries since `since`, rather than filter
        entry_date = datetime.date(*entry['updated_parsed'][:3])
        if entry_date >= since:
            keep.append(entry)

    for regression in keep:
        # TODO: Only open one issue per commit. A single commit may cause multiple regressions
        match = xpr.match(regression['summary'])
        if match:
            groups = match.groupdict()
            org = groups['GH_ORG']
            repo = groups['GH_REPO']
            sha = groups['SHA']

            if match['GH_ORG'] in GH_ORG_WHITELIST:
                commit = await gh.getitem(f'/repos/{org}/{repo}/commits/{sha}')
                data = format_issue(regression, commit)
                await gh.post(
                    f'/repos/{org}/{repo}/issues',
                    data=data
                )
                print(f"reported {sha}")
            else:
                print("Not reporting for", groups)

        else:
            print("Missing match for", regression)


def format_issue(regression, commit):
    title = "Possible performance regression in {sha}"
    template = textwrap.dedent("""
    Possible performance regression in {html_url}.

    Regression: {regression_url}
    Benchmark: {benchmark}

    cc @{author}.""")
    data = {
        'title': title.format(sha=commit['sha'][:6]),
        'body': template.format(
            html_url=commit['html_url'],
            author=commit['author']['login'],
            regression_url=regression['link'],
            benchmark=regression['title'],
        ),
    }
    return data


if __name__ == "__main__":
    app = web.Application()
    app.router.add_post("/", main)
    port = os.environ.get("PORT")
    if port is not None:
        port = int(port)

    web.run_app(app, port=port)

# import re
import datetime
import feedparser

# xpr = re.compile(
#     'New value: (?P<NEW>.*), old value: (?P<OLD>.*).<br>'
# )


def fetch(url):
    feed = feedparser.parse(url)
    return feed


def find_regressions(entries, since: datetime.date, cutoff=1.15):
    keep = []
    for entry in entries:
        entry_date = datetime.date(*entry['updated_parsed'][:3])
        if entry_date >= since:
            keep.append(entry)
    return keep

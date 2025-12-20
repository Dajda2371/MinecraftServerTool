import requests
from html.parser import HTMLParser

def last_buildtools_version():
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; MyScraper/1.0)"
    }

    response = requests.get("https://hub.spigotmc.org/jenkins/job/BuildTools/lastBuild/", headers=headers, timeout=10)
    html = response.text

    # print(html)

    class TitleParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_title = False
            self.title = None

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "title" and self.title is None:
                self.in_title = True

        def handle_endtag(self, tag):
            if tag.lower() == "title":
                self.in_title = False

        def handle_data(self, data):
            if self.in_title and self.title is None:
                self.title = data.strip()

    parser = TitleParser()
    parser.feed(html)

    # print(parser.title)

    buildtools_version = parser.title.lstrip("BuildTools #").rstrip(" - Spigot Jenkins")

    # print(f"Latest BuildTools version: {buildtools_version}")

    return buildtools_version

if __name__ == "__main__":
    last_buildtools_version()
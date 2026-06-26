import os
import requests
from bs4 import BeautifulSoup

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = "aime_pdfs"
DIR = os.path.join(PROJECT_DIR, OUTPUT_DIR)
os.makedirs(DIR, exist_ok=True)
print(PROJECT_DIR)
print(OUTPUT_DIR)
print(DIR)

url = "https://www.mathschool.com/blog/competitions/aime-problems-and-solutions"
response = requests.get(url)

print(response)  # prints the response status code (200 for success)
# print(response.text) # prints the HTML code

soup = BeautifulSoup(response.text, "html.parser")

pdf_links = []
titles = []

for a_tag in soup.find_all("a", href=True, title=True):
    # print(a_tag)
    # print(a_tag.attrs)
    # print(a_tag.name)
    print(a_tag["title"])
    href = a_tag["href"]

    if "hubs.ly" in href:
        pdf_links.append(href)
        titles.append(a_tag["title"])

for i in range(len(pdf_links)):
    safe_title = "".join(titles[i].split()) + ".pdf"
    filename = os.path.join(DIR, safe_title)

    print(f"Downloading {pdf_links[i]}")
    response = requests.get(pdf_links[i])

    with open(filename, "wb") as f:
        f.write(response.content)

    print(f"Saved to {filename}")

import pypandoc
import pandas as pd
import requests

from bs4 import BeautifulSoup
from datetime import datetime


def flatten(t):
    return [item for sublist in t for item in sublist if item]


def to_html(md):
    return pypandoc.convert_text(md, 'html5', format = 'md')


def create_url(cinema, day):
    day_code = "" if day == 0 else "d-{day}/".format(day = day)
    url = "https://www.allocine.fr/seance/{day_code}salle_gen_csalle={cinema}.html".format(day_code = day_code, cinema = cinema)

    return url


def get_url(url):
    response = requests.get(url)

    if response.ok:
        results = BeautifulSoup(response.text, "lxml")
        return results
    else:
        return


def parse_div(div):
    film_name = div.find('a', class_='meta-title-link').text
    synopsis = div.find('div', class_='synopsis').text.strip()
    showtimes_div = div.find('div', class_='showtimes-anchor')
    hours = showtimes_div.find_all('div', class_='showtimes-hour-block')

    try:
        showtimes = [hour.find('span', class_='showtimes-hour-item-value').text.strip() for hour in hours]
        seances = [(film_name, synopsis, showtime) for showtime in showtimes]
        return seances
    except:
        return


def parse_results(result):
    content = result.find("div", {"class": "showtimes-list-holder"})
    seances = content.find_all("div", {"class": "card entity-card entity-card-list movie-card-theater cf hred"})
    try:
        seances = flatten([parse_div(seance) for seance in seances])
        return seances
    except:
        return


def scrap_page(cinema, day):
    url = create_url(cinema, day)
    result = get_url(url)
    if result:
        seances = parse_results(result)
        return seances


def build_seances(cinema, results):
    results = results[results["cinema"] == cinema]
    return "/".join(results.heure.unique())


def generate_html_seance(results):
    cinemas = results.cinema.unique()
    html_chunk = ', '.join(["{cinema} {seances}".format(cinema = cinema, seances = build_seances(cinema, results)) for cinema in cinemas])
    return html_chunk

def generate_html_film(film, results):
    results = results[results["film"] == film]
    synopsis = results.synopsis.unique()[0]
    seances = generate_html_seance(results)

    html_chunk = "<details>\n<summary>{film} <small>[{seances}]</small></summary>{synopsis}</details>".format(film = film, seances = seances, synopsis = synopsis)

    return html_chunk


def generate_html_jour(jour, results):
    results = results[results["jour"] == jour]

    bloc = "\n".join([generate_html_film(film, results) for film in results.film.unique()]) + "\n\n"

    html_chunk = "<details>\n<summary>{jour}</summary>{bloc}</details>".format(jour = jour, bloc = bloc)

    return html_chunk


def read_file(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()

    return content


def main():
    today = datetime.today().weekday()
    days_by_index = {
        0: "Lundi",
        1: "Mardi",
        2: "Mercredi",
        3: "Jeudi",
        4: "Vendredi",
        5: "Samedi",
        6: "Dimanche"
        }

    days = range(7)

    cinemas_by_code = {
        "C0020": "filmothèque",
        "C0071": "écoles",
        "C0054": "arlequin",
        "C0015": "christine",
        "C2954": "bibliothèque"
        }

    results = {
      (cinema, day): scrap_page(cinema, day)
      for cinema in cinemas_by_code
      for day in days
      }

    results = {key: value for key, value in results.items() if value}

    results = [
      (cinemas_by_code[cinema], days_by_index[(day + today) % 7], film_name, synopsis, showtime)
      for (cinema, day), seances in results.items()
      for (film_name, synopsis, showtime) in seances
      ]

    results = pd.DataFrame(results, columns = ("cinema", "jour", "film", "synopsis", "heure"))
    html_chunks = [generate_html_jour(jour, results) for jour in results.jour.unique()]

    text = \
        read_file("programs/header.html") \
        + "\n".join(html_chunks) \
        + read_file("programs/footer.html")

    with open("output/index.html", "w") as f:
        f.write(text)

if __name__ == "__main__":
    main()


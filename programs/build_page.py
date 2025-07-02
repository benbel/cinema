import os
import jinja2
import pandas as pd
import pypandoc
import requests

from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter, Retry

# Import configuration data
from programs.config_data import CINEMAS_BY_CODE, DAYS_BY_INDEX

# Constants
OUTPUT_DIR = "output"
IMAGE_DIR_NAME = ""  # Images will be in OUTPUT_DIR directly for simplicity with current template
TEMPLATES_DIR = "./templates"  # Relative to where the script is run from (project root)
ALLOCINE_BASE_URL = "https://www.allocine.fr/seance/salle_gen_csalle={cinema}.html#shwt_date={date}{page_code}"
DEFAULT_RETRY_TOTAL = 20
DEFAULT_RETRY_BACKOFF_FACTOR = 0.1
DEFAULT_RETRY_STATUS_FORCELIST = [500, 502, 503, 504]
NUM_DAYS_TO_SCRAPE = 7
PAGES_TO_SCRAPE = [1, 2] # Allocine usually doesn't have more than 2 pages for a given day/cinema

# Initialize Jinja2 environment
template_loader = jinja2.FileSystemLoader(searchpath=TEMPLATES_DIR)
template_env = jinja2.Environment(loader=template_loader, autoescape=jinja2.select_autoescape(['html', 'xml']))


def flatten_list(list_of_lists):
    """Flattens a list of lists into a single list, removing None items."""
    return [item for sublist in list_of_lists for item in sublist if item]


def normalize_path_component(filename_component):
    """Removes problematic characters from a string to make it a valid path component."""
    # Characters considered problematic for file/path names
    problem_chars = ['"', ":", "<", ">", "|", "*", "?", "\r", "\n", "/"] # Added /
    
    for problem_char in problem_chars:
        filename_component = filename_component.replace(problem_char, "")
    return filename_component.strip()


def create_allocine_url(cinema_code, date_obj, page_num):
    """Creates the URL for a specific cinema, date, and page on Allocine."""
    page_code_str = "" if page_num == 1 else f"?page={page_num}"
    date_str = date_obj.strftime('%Y-%m-%d')
    return ALLOCINE_BASE_URL.format(cinema=cinema_code, date=date_str, page_code=page_code_str)


def fetch_url_content(url, session):
    """Fetches content from a URL using the provided session."""
    try:
        response = session.get(url, timeout=10)  # Added timeout
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        return BeautifulSoup(response.text, "lxml")
    except requests.exceptions.RequestException as e:
        # print(f"Error fetching {url}: {e}") # Optional: Log error
        return None


def parse_showtime_hour(hour_element):
    """Parses the showtime hour from a BeautifulSoup element."""
    singular = hour_element.find('span', class_='showtimes-hour-item-value')
    plural = hour_element.find('span', class_='showtimes-hours-item-value')

    if singular:
        return singular.text.strip()
    if plural:
        return plural.text.strip()
    return None


def download_image(url, filepath, session):
    """Downloads an image from a URL and saves it to a filepath."""
    if not os.path.isfile(filepath):
        try:
            response = session.get(url, timeout=10)  # Added timeout
            response.raise_for_status()
            # Ensure output directory for images exists
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return True
        except requests.exceptions.RequestException as e:
            # print(f"Error downloading image {url}: {e}") # Optional: Log error
            return False
    return False


def parse_movie_div(div_element, session):
    """Parses movie information from a BeautifulSoup div element."""
    try:
        film_name_tag = div_element.find('a', class_='meta-title-link')
        film_name = film_name_tag.text.strip() if film_name_tag else "Unknown Film"

        synopsis_tag = div_element.find('div', class_='synopsis')
        synopsis = synopsis_tag.text.strip() if synopsis_tag else "No synopsis available."

        showtimes_div = div_element.find('div', class_='showtimes-anchor')
        hour_elements = showtimes_div.find_all('div', class_='showtimes-hour-block') if showtimes_div else []

        img_tag = div_element.find('img', class_='thumbnail-img')
        thumbnail_url = img_tag.get('data-src', img_tag.get('src')) if img_tag else None

        # Image path logic: save directly into OUTPUT_DIR
        # The template will use <img src="normalized_film_name.jpg">
        normalized_film_name = normalize_path_component(film_name)
        image_filename = f"{normalized_film_name}.jpg"
        # The film_path for the template will be just the filename, as index.html is in OUTPUT_DIR
        image_save_path = os.path.join(OUTPUT_DIR, image_filename)

        if thumbnail_url:
            download_image(thumbnail_url, image_save_path, session)

        release_date_tag = div_element.find('span', class_='date')
        release_date = release_date_tag.text.strip() if release_date_tag else ""

        showtimes = [parse_showtime_hour(hour) for hour in hour_elements]
        showtimes = [st for st in showtimes if st]  # Filter out None values

        if not showtimes:  # Skip movie if no showtimes found for it in this block
            return []

        return [(film_name, release_date, synopsis, showtime, image_filename) for showtime in showtimes]
    except Exception as e:
        print(f"Error parsing movie div for '{film_name}': {e}")
        return []


def parse_page_results(beautifulsoup_results, session):
    """Parses all movie results from a page."""
    if not beautifulsoup_results:
        return []

    content_holder = beautifulsoup_results.find("div", {"class": "showtimes-list-holder"})
    if not content_holder:
        return []

    movie_card_classes = "card entity-card entity-card-list movie-card-theater cf hred"
    movie_cards = content_holder.find_all("div", {"class": movie_card_classes})

    all_seances_for_page = []
    for seance_div in movie_cards:
        all_seances_for_page.extend(parse_movie_div(seance_div, session))
    return all_seances_for_page


def scrape_single_page(cinema_code, date_obj, page_num, session):
    """Scrapes showtimes for a single cinema, date, and page."""
    url = create_allocine_url(cinema_code, date_obj, page_num)
    soup_content = fetch_url_content(url, session)
    if soup_content:
        return parse_page_results(soup_content, session)
    return []


def build_seances_string_for_film(cinema_name, film_results_df):
    """Builds a string of showtimes for a given cinema and film results."""
    cinema_specific_results = film_results_df[film_results_df["cinema"] == cinema_name]
    unique_hours = sorted(cinema_specific_results.heure.unique())
    return "/".join(unique_hours)


def generate_seance_summary_for_film(film_results_df):
    """Generates a summary string of seances grouped by cinema for a film."""
    cinemas = sorted(film_results_df.cinema.unique())
    seance_strings = [
        f"{cinema_name} {build_seances_string_for_film(cinema_name, film_results_df)}<br>"
        for cinema_name in cinemas
    ]
    return "\n".join(seance_strings)


def render_film_html(film_name, film_data_df):
    """Renders HTML for a single film using its template."""
    film_template = template_env.get_template("film_section.html")

    # All rows in film_data_df are for the same film, so pick from the first
    synopsis = film_data_df.synopsis.iloc[0]
    release_date = film_data_df.jour_sortie.iloc[0]
    # image_filename is now consistent across all rows for the same film
    image_filename = film_data_df.image_filename.iloc[0]

    seances_summary = generate_seance_summary_for_film(film_data_df)

    # film_path for template is just the filename, as index.html is in OUTPUT_DIR
    # and images are also in OUTPUT_DIR.
    # Remove .jpg from image_filename because template adds it.
    film_path_for_template = image_filename.replace(".jpg", "")

    return film_template.render(
        film_name=film_name,
        seances=seances_summary,
        film_path=film_path_for_template,
        release_date=release_date,
        synopsis=synopsis
    )


def render_day_html(day_name, day_data_df):
    """Renders HTML for a single day, including all its films."""
    day_template = template_env.get_template("day_section.html")

    film_html_blocks = [
        render_film_html(film_name, film_df)
        for film_name, film_df in sorted(day_data_df.groupby("film"))
    ]
    films_html_content = "\n".join(film_html_blocks)

    return day_template.render(day=day_name, films_html=films_html_content)


def create_http_session():
    """Creates a requests Session with retry logic."""
    session = requests.Session()
    retries = Retry(
        total=DEFAULT_RETRY_TOTAL,
        backoff_factor=DEFAULT_RETRY_BACKOFF_FACTOR,
        status_forcelist=DEFAULT_RETRY_STATUS_FORCELIST
    )
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session


def main():
    """Main function to scrape data and generate HTML."""
    # Ensure the main output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    http_session = create_http_session()

    current_date = datetime.today()
    dates_to_scrape = [current_date + timedelta(days=k) for k in range(NUM_DAYS_TO_SCRAPE)]

    scraped_data = []
    for cinema_code in CINEMAS_BY_CODE:
        for date_obj in dates_to_scrape:
            for page_num in PAGES_TO_SCRAPE:
                page_seances = scrape_single_page(cinema_code, date_obj, page_num, http_session)
                if page_seances:
                    # Add cinema name and day name to each seance record
                    cinema_name = CINEMAS_BY_CODE[cinema_code]
                    day_name = DAYS_BY_INDEX[date_obj.weekday()]
                    for seance in page_seances:
                        # seance is (film_name, release_date, synopsis, showtime, image_filename)
                        scraped_data.append((cinema_name, day_name) + seance)
                else:  # If a page has no results, likely no more pages for this cinema/day
                    break

    if not scraped_data:
        index_template = template_env.get_template("index.html")
        final_html = index_template.render(
            content="<p>No showtime data available at the moment.</p>"
        )
        print(final_html)
        return

    df_columns = [
        "cinema", "jour", "film", "jour_sortie",
        "synopsis", "heure", "image_filename"
    ]
    results_df = pd.DataFrame(scraped_data, columns=df_columns)

    # Sort days chronologically starting from today
    index_by_day = {day: index for index, day in DAYS_BY_INDEX.items()}
    today_weekday_index = current_date.weekday()

    # Create a categorical type for days to ensure correct sorting
    day_categories = sorted(
        results_df.jour.unique(),
        key=lambda d: (index_by_day[d] - today_weekday_index + 7) % 7
    )
    results_df['jour'] = pd.Categorical(
        results_df['jour'], categories=day_categories, ordered=True
    )
    results_df = results_df.sort_values(by="jour")  # Sort DataFrame by this categorical "jour"

    day_html_blocks = [
        render_day_html(day_name, day_df)
        for day_name, day_df in results_df.groupby("jour", observed=True)  # Use observed=True with categorical
    ]

    main_content_html = "\n".join(day_html_blocks)
    index_template = template_env.get_template("index.html")
    final_html = index_template.render(content=main_content_html)

    print(final_html)

if __name__ == "__main__":
    main()
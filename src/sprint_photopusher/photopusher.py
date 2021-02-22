"""Module for cli application monitoring directory and send json to webserver."""
from ftplib import FTP
import logging
import os
import time
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from PIL.ExifTags import TAGS

import click

from dotenv import load_dotenv

import pandas as pd

import requests

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from . import __version__

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])
load_dotenv()
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO")

logging.basicConfig(
    level=LOGGING_LEVEL,
    format="%(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@click.command(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=__version__)
@click.argument("url", type=click.STRING)
@click.option(
    "-d",
    "--directory",
    default=os.getcwd(),
    help="Relative path to the directory to watch",
    show_default=True,
    type=click.Path(
        exists=True,
        file_okay=False,
    ),
)
def cli(url: str, directory: Any) -> None:
    """CLI for monitoring directory and send content of files as json to webserver URL.

    URL is the url to a webserver exposing an endpoint accepting your json.

    To stop the photopusher, press Control-C.
    \f
    Args:
        url: the URL to a webserver exposing an endpoint accepting json.
        directory: relative path to the directory to watch
    """  # noqa: D301
    # Check if webserver is alive:
    if _webserver_allive(url):
        click.echo(f"\nWorking directory {os.getcwd()}")
        click.echo(f"Watching directory {os.path.join(os.getcwd(), directory)}")
        click.echo(f"Sending data to webserver at {url}")
    else:
        exit(2)

    monitor = FileSystemMonitor(directory=directory, url=url)
    monitor.start(loop_action=lambda: time.sleep(100))

    click.echo("Bye!\n")


def _webserver_allive(url: str) -> bool:
    try:
        _url = f"{url}/ping"
        logging.debug(f"Trying to ping webserver at {url}")
        response = requests.get(_url)
        if response.status_code == 200:
            logging.info(f"Connected to {url}")
            return True
        else:
            logging.error(
                f"Webserver respondend with not ok status_code: {response.status_code}"
            )
    except Exception:
        logging.error("Webserver not available. Exiting....")
    return False


class FileSystemMonitor:
    """Monitor directory and send content of files as json to webserver URL."""

    def __init__(self, url: str, directory: Any) -> None:
        """Do init monitor of directory and verify url."""
        self.url = url
        self.path = directory
        self.handler = EventHandler(url)

    def start(self, loop_action: Any) -> None:
        """Start the monitor and start oberserver loop_action."""
        observer = Observer()
        observer.schedule(self.handler, self.path, recursive=True)
        observer.start()
        try:
            while True:
                loop_action()
        except KeyboardInterrupt:
            observer.stop()

        observer.join()


class EventHandler(FileSystemEventHandler):
    """Custom eventhandler class."""

    def __init__(self, url: str) -> None:
        """Initalize the monitor."""
        super(EventHandler, self).__init__()
        self.url = url

    def on_any_event(self, event: FileSystemEvent) -> None:
        """Handle any events primarily for logging."""
        super(EventHandler, self).on_any_event(event)

        what = "directory" if event.is_directory else "file"
        logging.info(
            f"{event.event_type} {what}: {event.src_path}",
        )

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        super(EventHandler, self).on_created(event)

        if not event.is_directory:
            handle_photo(self.url, event.src_path)


def ftp_upload(infile: str, outfile: str) -> str:
    """Upload file to ftp server, return url to file."""

    photoftpdest = os.environ["PHOTO_FTP_DEST"]
    logging.debug(f"FTP dest: {photoftpdest}")
    photoftpuid = os.environ["PHOTO_FTP_UID"]
    logging.debug(f"FTP user: {photoftpuid}")
    photoftppw = os.environ["PHOTO_FTP_PW"]

    session = FTP(photoftpdest, photoftpuid, photoftppw)
    file = open(infile, "rb")  # file to send
    session.storbinary("STOR " + outfile, file)  # send the file
    file.close()  # close file and FTP
    session.quit()

    url = "http://www.harnaes.no/sprint/" + outfile
    logging.info(f"FTP Upload file {url}")
    return url


def create_thumb(infile: str, outfile) -> None:
    """Create thumb from infile."""
    size = (180, 180)

    try:
        with Image.open(infile) as im:
            logging.debug(f"Photo size: {im.size}")
            im.thumbnail(size)
            im.save(outfile, "JPEG")
            logging.info(f"Created thumb: {outfile}")
    except OSError:
        logging.info(f"cannot create thumbnail for {infile} {OSError}")


def watermark_image(infile: str, outfile: str) -> None:
    """Watermark to infile and move to output folder."""
    try:
        tatras = Image.open(infile)
        idraw = ImageDraw.Draw(tatras)
        text = "Ragdesprinten 2021, Kjelsås IL"

        font = ImageFont.truetype("Pillow/Tests/fonts/FreeMono.ttf", size=120)
        idraw.text((tatras.width / 2, tatras.height - 200), text, font=font)
        tatras.save(outfile)
        logging.info("Watermarked file: " + outfile)
    except Exception:
        logging.info("Unable to watermark image ")
        logging.info(Exception)


def create_tags(infile: str) -> dict:
    """Read infile, return dict with relevant tags."""
    _tags = {}
    try:
        with Image.open(infile) as im:
            exifdata = im.getexif()
            # iterating over all EXIF data fields
            for tag_id in exifdata:
                # get the tag name, instead of human unreadable tag id
                tag = TAGS.get(tag_id, tag_id)
                data = exifdata.get(tag_id)
                if tag == "GPSInfo":
                    _tags[tag] = data
                elif tag == "DateTime":
                    _tags[tag] = data
            # look for information in filename
            locationtags = ["start", "race", "finish", "prize", "press"]
            _filename = infile.lower()
            for location in locationtags:
                if location in _filename:
                    _tags["Location"] = location
                    logging.debug(f"Location found: {location}")
    except OSError:
        logging.info("Image error ", OSError)
    return _tags


def handle_photo(url: str, src_path: Any) -> None:
    """Convert file content to json and push to webserver at url."""
    _url, datafile_type = find_url_datafile_type(url, src_path)
    logging.info(f"Server url: {_url} - datafile: {datafile_type}")

    if _url:

        try:
            # TODO - need to enhance name & move to folder thumbs
            filename = src_path.split(os.path.sep)[-1]

            # create thumb
            directory = src_path.replace("input/" + filename, "")
            outfile_thumb = directory + "thumbs/thumb_" + filename
            create_thumb(src_path, outfile_thumb)

            # add watermark
            outfile_main = src_path.replace("input/", "output/")
            watermark_image(src_path, outfile_main)

            # upload files
            ftp_upload(outfile_main, filename)
            ftp_upload(outfile_thumb, "thumb_" + filename)

            # update webserver and link to results
            tags = create_tags(src_path)
            logging.info(f"Tags {tags}")

            body = "test"
            headers = {"content-type": "application/json; charset=utf-8"}
            logging.info(f"sending body {body}")
            # response = requests.post(_url, headers=headers, data=body)
            # if response.status_code == 201:
            #    logging.debug(
            #        f"Converted and pushed {src_path} -> {response.status_code}"
            #    )
            # else:
            #    logging.error(f"got status {response.status_code}")
        except Exception as e:
            logging.error(f"got exceptions {e}")
    else:
        logging.info(f"Ignoring event on file {src_path}")


def find_url_datafile_type(url: str, src_path: str) -> tuple:
    """Determine and return url and datafile_type based src_path."""
    datafile_type = ""
    _url = ""
    if ".jpg" in src_path.split(os.path.sep)[-1]:
        _url = f"{url}/photo"
        datafile_type = "jpg"
    elif ".JPG" in src_path.split(os.path.sep)[-1]:
        _url = f"{url}/photo"
        datafile_type = "jpg"
    return _url, datafile_type


def convert_csv_to_json(src_path: str, datafile_type: str) -> str:
    """Convert content of src_path datafile_type file, return json."""
    if datafile_type == "deltakere":
        # read the csv into a dataframe, and skip the first row:
        df = pd.read_csv(src_path, sep=";", encoding="utf-8", dtype=str)
        # drops the first row:
        df = df.iloc[1:]
        # drop all rows with no value:
        df.dropna(subset=["Startnr"], inplace=True)
        # drop columns with no values:
        df.dropna(how="all", axis="columns", inplace=True)

    if datafile_type == "innstillinger":
        # read the csv into a dataframe, and skip the first row:
        df = pd.read_csv(src_path, sep=";", encoding="utf-8", dtype=str)
        # drop all rows with no value:
        df.dropna(subset=["Parameter"], inplace=True)
        # drop columns with no values:
        df.dropna(how="all", axis="columns", inplace=True)

    # Kjoreplan.csv:
    if datafile_type == "kjoreplan":
        # read the csv into a dataframe, and skip the first row:
        df = pd.read_csv(src_path, sep=";", encoding="utf-8", dtype=str)
        # drop all rows with no value in (Heat) Index:
        df.dropna(subset=["Index"], inplace=True)
        # drop columns with no values:
        df.dropna(how="all", axis="columns", inplace=True)

    # Klasser.csv:
    if datafile_type == "klasser":
        # read the csv into a dataframe, and skip the first row:
        df = pd.read_csv(src_path, sep=";", encoding="utf-8", dtype=str)
        # drops the first row:
        df = df.iloc[1:]
        # drop all rows with no value in Klasse:
        df.dropna(subset=["Klasse"], inplace=True)
        # drop columns with no values:
        df.dropna(how="all", axis="columns", inplace=True)

    # Resultat heat:
    if datafile_type == "resultat_heat":
        # read the csv into a dataframe, and skip the first two rows:
        df = pd.read_csv(src_path, sep=";", skiprows=2, encoding="utf-8", dtype=str)
        # drop all rows with no value in Plass:
        df.dropna(subset=["Plass"], inplace=True)

    # Resultatliste:
    if datafile_type == "resultat":
        # read the csv into a dataframe, and skip the first row:
        df = pd.read_csv(src_path, sep=";", skiprows=1, encoding="utf-8", dtype=str)
        # drop all rows with no value in Plass:
        df.dropna(subset=["Plass"], inplace=True)

    # Startlists:
    if datafile_type == "start":
        # read the csv into a dataframe, and skip the first two rows:
        df = pd.read_csv(src_path, sep=";", skiprows=2, encoding="utf-8", dtype=str)
        # drop "headers" pr heat, i.e. rows with value "Heat" in column "Heat":
        df = df[df["Heat"] != "Heat"]
        # drop all rows with no value in Pos:
        df.dropna(subset=["Pos"], inplace=True)

    # For all types of files:
    # reset index:
    df.reset_index(drop=True, inplace=True)
    logging.debug(df.to_json(orient="records", force_ascii=True))
    # convert dataframe to json and return:
    return df.to_json(orient="records", force_ascii=True)

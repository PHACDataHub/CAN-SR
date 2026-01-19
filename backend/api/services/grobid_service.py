import os
import logging

from grobid_client.grobid_client import GrobidClient
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

COLORS = {
    "persName": "rgba(0, 0, 255, 1)",  # Blue
    "s": "rgba(139, 0, 0, 1)",  # Green
    "p": "rgba(139, 0, 0, 1)",  # Dark red
    "ref": "rgba(255, 255, 0, 1)",  # ??
    "biblStruct": "rgba(139, 0, 0, 1)",  # Dark Red
    "head": "rgba(139, 139, 0, 1)",  # Dark Yellow
    "formula": "rgba(255, 165, 0, 1)",  # Orange
    "figure": "rgba(165, 42, 42, 1)",  # Brown
    "title": "rgba(255, 0, 0, 1)",  # Red
    "affiliation": "rgba(255, 165, 0, 1)"  # red-orengi
}


def get_color(name, param):
    color = COLORS[name] if name in COLORS else "rgba(128, 128, 128, 1.0)"
    if param:
        color = color.replace("1)", "0.4)")

    return color

def exclude_tags(tag):
    ret = False
    ret |= tag.name != 'abstract' # exclude the abstract
    return ret

class GrobidService:
    def __init__(self):

        self.base_service_url = os.getenv(
            "GROBID_SERVICE_URL", "http://grobid-service:8000"
        )

        grobid_client = GrobidClient(
            grobid_server=self.base_service_url,
            batch_size=1000,
            coordinates=["p", "s", "persName", "biblStruct", "figure", "formula", "head", "note", "title", "ref",
                        "affiliation"],
            sleep_time=5,
            timeout=240,
            check_server=True
        )
        self.grobid_client = grobid_client

    async def process_structure(self, input_path) -> (dict, list):
        pdf_file, status, text = self.grobid_client.process_pdf("processFulltextDocument",
                                                                input_path,
                                                                consolidate_header=True,
                                                                consolidate_citations=False,
                                                                segment_sentences=True,
                                                                tei_coordinates=True,
                                                                include_raw_citations=False,
                                                                include_raw_affiliations=False,
                                                                generateIDs=True)

        if status != 200:
            return

        coordinates = await self.get_coordinates(text)
        pages = await self.get_pages(text)

        return coordinates, pages

    @staticmethod
    def box_to_dict(box, color=None, type=None, text=None):

        item = {"page": box[0], "x": box[1], "y": box[2], "width": box[3], "height": box[4]}
        if color is not None:
            item['color'] = color

        if type:
            item['type'] = type

        if text:
            item['text'] = text

        return item

    async def get_coordinates(self, text):
        soup = BeautifulSoup(text, 'xml')

        # exclude certain tag names
        all_blocks_with_coordinates = soup.find('text').find_all(coords=True)
        # all_blocks_with_coordinates = soup.find_all()

        # if use_sentences:
        #     all_blocks_with_coordinates = filter(lambda b: b.name != "p", all_blocks_with_coordinates)

        coordinates = []
        count = 0
        for block_id, block in enumerate(all_blocks_with_coordinates):
            for box in filter(lambda c: len(c) > 0 and c[0] != "", block['coords'].split(";")):
                coordinates.append(
                    self.box_to_dict(
                        box.split(","),
                        get_color(block.name, count % 2 == 0),
                        type=block.name,
                        text=block.text
                    ),
                )
            count += 1
        return coordinates

    async def get_pages(self, text):
        soup = BeautifulSoup(text, 'xml')
        pages_infos = soup.find_all("surface")

        pages = [{'width': float(page['lrx']) - float(page['ulx']), 'height': float(page['lry']) - float(page['uly'])}
             for page in pages_infos]

        return pages

# Global instance
grobid_service = GrobidService()

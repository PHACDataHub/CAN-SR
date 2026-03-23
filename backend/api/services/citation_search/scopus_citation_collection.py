import requests

class ScopusDataProcessor:
    def __init__(self, api_key, base_url):
        self._api_key = api_key
        self._URL = base_url
        # self._inst_token_ = insttoken
        self.data = []

    def fetch_data(self, start, search_term):
        params = { "query": search_term, 
                  "apiKey": self._api_key, 
                  "count": 25, 
                  "start": start, 
                  "view": "COMPLETE"} 
        response = requests.get(self._URL, params=params)
        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()

    def process_entry(self, entry):
        pdf_link_call = self.get_open_access_link(entry.get("prism:doi"))
        return {
            "Refid": entry.get("dc:identifier"),
            "Author": ", ".join([author["authname"] for author in entry.get("author", [])]),
            "Title": entry.get("dc:title"),
            "Abstract": entry.get("dc:description"),
            "Accession Number": entry.get("eid"),
            "Alternate Title": None,
            "Article Number": entry.get("article-number"),
            "Author Address": None,
            "Database": "Scopus",
            "Database Provider": "Elsevier",
            "Date": entry.get("prism:coverDate"),
            "DOI": entry.get("prism:doi"),
            "Epub Date": None,
            "ISSN": entry.get("prism:issn"),
            "Issue": entry.get("prism:issueIdentifier"),
            "Journal": entry.get("prism:publicationName"),
            "Keywords": entry.get("authkeywords").replace(" |", ",") if entry.get("authkeywords") != None else None,
            "Language": None,
            "Notes": None,
            "Original Publication": None,
            "Pages": entry.get("prism:pageRange"),
            "Place Published": None,
            "PMCID": None,
            "Publisher": entry.get("prism:publicationName"),
            "Reprint Edition": None,
            "Secondary Author": None,
            "Short Title": None,
            "Translated Title": None,
            "Type": entry.get("subtypeDescription"),
            "Type of Work": entry.get("prism:aggregationType"),
            "URL": entry.get("prism:url"),
            "Volume": entry.get("prism:volume"),
            "Year": int(entry.get("prism:coverDate").split("-")[0]),
            "User": None,
            "Level": None,
            "Open Access Link": pdf_link_call,
            "Is this article primary research?": None,
            "Is this article on the human population?": None,
            "Is the main focus of this study about measles disease?": None,
            "Measles aka rubeola, Morbilli, red measles, English measles": None
        }

    def consume_api(self, search_term, delay=1):
        res_data = self.fetch_data(0)

        total_results = int(res_data.get("search-results", {}).get("opensearch:totalResults"))
        for start in range(0, total_results, 25):
            res_data = self.fetch_data(start, search_term)
            entries = res_data.get("search-results", {}).get("entry", [])
            for entry in entries:
                self.data.append(self.process_entry(entry))

    def get_open_access_link(self, doi):
        if not doi:
            return None

        url = f"https://api.openaccessbutton.org/find?id={doi}"
        response = requests.get(url)

        if response and response.status_code == 200:
            data = response.json()
            link = data.get('url', None)
            if link and 'pdf' in link.lower():
                return link
        return None
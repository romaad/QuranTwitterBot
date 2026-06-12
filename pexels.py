"""
Pexels API client for fetching background nature videos.

Docs: https://www.pexels.com/api/
Set the ``PEXELS_API_KEY`` environment variable before use.
"""
import logging
import random

import requests

log = logging.getLogger(__name__)

PEXELS_VIDEO_SEARCH_URL = "https://api.pexels.com/videos/search"


class PexelsClient:
    """Thin wrapper around the Pexels Videos API."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def fetch_video(
        self,
        query: str,
        output_path: str,
        orientation: str = "portrait",
        per_page: int = 15,
    ) -> str:
        """
        Search Pexels for a *query* video (excluding human subjects) and
        download it to *output_path*.

        Parameters
        ----------
        query:
            Search term, e.g. ``"nature"`` or ``"wildlife"``.
        output_path:
            Destination file path for the downloaded MP4.
        orientation:
            ``"portrait"`` (default, 9:16 mobile), ``"landscape"``, or ``"square"``.
        per_page:
            Number of results to retrieve; a random one is selected.

        Returns *output_path* on success.
        Raises ``ValueError`` if no results are found or no suitable video file exists.
        Raises ``requests.HTTPError`` if the API or download request fails.
        """
        headers = {"Authorization": self.api_key}
        params = {
            "query": query,
            "orientation": orientation,
            "per_page": per_page,
            "page": random.randint(1, 10), # Randomize the page to get a bigger variety
            "humans": 0,
        }
        response = requests.get(
            PEXELS_VIDEO_SEARCH_URL, headers=headers, params=params, timeout=30
        )
        response.raise_for_status()

        videos = response.json().get("videos", [])
        if not videos:
            raise ValueError(f"No Pexels videos found for query '{query}'")

        video = random.choice(videos)

        # Pick the highest-resolution MP4 link available
        video_files = [
            vf
            for vf in video.get("video_files", [])
            if vf.get("file_type") == "video/mp4" and vf.get("link")
        ]
        if not video_files:
            raise ValueError(
                f"No MP4 file found for Pexels video id={video.get('id')}"
            )

        best = max(
            video_files, key=lambda vf: (vf.get("width", 0) * vf.get("height", 0))
        )
        link = best["link"]

        log.debug("Downloading Pexels video %s → %s", link, output_path)
        dl = requests.get(link, timeout=120, stream=True)
        dl.raise_for_status()
        with open(output_path, "wb") as fh:
            for chunk in dl.iter_content(chunk_size=1 << 20):
                fh.write(chunk)

        log.info("Pexels nature video saved to %s", output_path)
        return output_path

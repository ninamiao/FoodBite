"""Fetch one public webpage through Bright Data Web Unlocker.

This script sends at most one request. It does nothing on the network unless
you pass --confirm-request. --dry-run only prints the request shape.

Official Direct API (verified from Bright Data's docs):
https://docs.brightdata.com/api-reference/rest-api/unlocker/unlock-website
"""

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

# Direct API access. Do not use the async endpoint: that needs a second call.
API_URL = "https://api.brightdata.com/request"
# Bright Data's error guide says a client timeout under 180 seconds can cut
# off a slow unlock before the error is returned. This is one wait, not a retry.
REQUEST_TIMEOUT_SECONDS = 180
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ScrapeError(Exception):
    """A problem we can explain without showing secrets."""


def load_credentials() -> tuple[str, str]:
    """Read the API key and zone from the environment or the project .env file."""
    load_dotenv(PROJECT_ROOT / ".env")
    api_key = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
    zone = os.environ.get("BRIGHTDATA_ZONE", "").strip()

    missing = []
    if not api_key:
        missing.append("BRIGHTDATA_API_KEY")
    if not zone:
        missing.append("BRIGHTDATA_ZONE")
    if missing:
        names = ", ".join(missing)
        raise ScrapeError(
            f"Missing {names}. Add them to .env in the project root. "
            "The names are listed in .env.example. The values were not printed."
        )
    return api_key, zone


def validate_target_url(url: str) -> str:
    """Reject a URL before any request. The API requires http or https."""
    cleaned_url = url.strip()
    try:
        parsed = urlparse(cleaned_url)
        hostname = parsed.hostname
        parsed.port  # Validate that an explicitly supplied port is numeric and in range.
    except ValueError as exc:
        raise ScrapeError("The URL contains an invalid host or port.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not hostname
        or any(character.isspace() for character in cleaned_url)
    ):
        raise ScrapeError(
            "The URL must include http:// or https:// and a hostname, "
            "for example https://example.com/events."
        )
    return cleaned_url


def build_payload(zone: str, target_url: str) -> dict[str, str]:
    """Body fields required by the Web Unlocker Direct API."""
    return {
        "zone": zone,
        "url": target_url,
        "format": "raw",
    }


def build_headers(api_key: str) -> dict[str, str]:
    """Bearer authentication, as documented. The key stays in this header only."""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def describe_dry_run(zone: str, target_url: str, confirm_also_set: bool) -> str:
    """Request details safe to print. The API key is never included."""
    lines = [
        "Dry run: no request will be sent, and no Bright Data credits will be used.",
    ]
    if confirm_also_set:
        lines.append(
            "--confirm-request was also set. Dry run wins, so nothing will be sent."
        )
    lines.extend(
        [
            f"Endpoint: POST {API_URL}",
            "Header Authorization: Bearer [redacted]",
            "Header Content-Type: application/json",
            "BRIGHTDATA_API_KEY: set",
            f"BRIGHTDATA_ZONE: {zone}",
            "JSON body:",
            f"  zone: {zone}",
            f"  url: {target_url}",
            "  format: raw",
            f"Timeout: {REQUEST_TIMEOUT_SECONDS} seconds",
            "Redirects: not followed",
        ]
    )
    return "\n".join(lines)


def fetch_html(target_url: str, api_key: str, zone: str) -> str:
    """Send exactly one Web Unlocker request and return the page HTML."""
    try:
        response = requests.post(
            API_URL,
            headers=build_headers(api_key),
            json=build_payload(zone, target_url),
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.Timeout as exc:
        raise ScrapeError(
            "The request timed out after "
            f"{REQUEST_TIMEOUT_SECONDS} seconds. No retry was attempted."
        ) from exc
    except requests.RequestException as exc:
        raise ScrapeError(
            "The request failed before Bright Data returned a response. "
            "No retry was attempted. "
            f"Details: {exc}"
        ) from exc

    return read_html_response(response)


def read_html_response(response: requests.Response) -> str:
    """Turn one Direct API response into HTML, or raise a clear error.

    After a request is accepted, Bright Data keeps the outer HTTP status at
    200 and puts the target page's status in the x-brd-status-code header.
    Unlock failures also set x-brd-error. A 400 or 401 is rejected before
    that and has no x-brd-* headers.
    """
    if response.status_code == 401:
        raise ScrapeError(
            "Bright Data rejected the API key (HTTP 401). "
            "Check BRIGHTDATA_API_KEY in .env."
        )
    if response.status_code == 400:
        raise ScrapeError(
            "Bright Data rejected the request (HTTP 400). "
            "Check BRIGHTDATA_ZONE and the target URL."
        )
    if response.status_code != 200:
        raise ScrapeError(
            f"Bright Data returned HTTP {response.status_code}. "
            "The redirect was not followed, and no retry was attempted."
        )

    unlock_error = response.headers.get("x-brd-error")
    if unlock_error:
        error_code = (
            response.headers.get("x-brd-error-code")
            or response.headers.get("x-brd-err-code")
            or "not provided"
        )
        target_status = response.headers.get("x-brd-status-code", "not provided")
        raise ScrapeError(
            "Bright Data could not unlock this page. "
            f"x-brd-status-code: {target_status}. "
            f"error code: {error_code}. See Bright Data's response headers for details."
        )

    target_status = response.headers.get("x-brd-status-code")
    if target_status is not None:
        try:
            status_code = int(target_status)
        except ValueError as exc:
            raise ScrapeError(
                "Bright Data returned a non-numeric x-brd-status-code: "
                f"{target_status!r}."
            ) from exc
        if status_code < 200 or status_code >= 300:
            raise ScrapeError(
                f"The target page returned HTTP {status_code} "
                "(header x-brd-status-code). No HTML was printed."
            )

    html = response.text
    if not html.strip():
        raise ScrapeError("Bright Data returned an empty response body.")
    return html


def save_html(target_url: str, html: str) -> Path:
    """Save HTML under data/ without replacing any existing file."""
    parsed = urlparse(target_url)
    host = re.sub(r"[^A-Za-z0-9_-]+", "_", parsed.hostname or "page").strip("_")
    path_slug = re.sub(r"[^A-Za-z0-9_-]+", "_", parsed.path).strip("_")
    stem = "_".join(part for part in (host, path_slug) if part) or "page"
    stem = stem[:100]
    output_dir = PROJECT_ROOT / "data"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Exclusive creation makes the no-overwrite guarantee hold even if two
    # scraper processes try to save the same target at the same time.
    for suffix in range(1, 10000):
        name = f"{stem}.html" if suffix == 1 else f"{stem}_{suffix}.html"
        output_path = output_dir / name
        try:
            with output_path.open("x", encoding="utf-8", newline="") as output_file:
                output_file.write(html)
            return output_path
        except FileExistsError:
            continue
    raise ScrapeError(f"Could not find an unused filename in {output_dir}.")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch one public webpage through Bright Data Web Unlocker. "
            "Sends a request only when --confirm-request is given."
        )
    )
    parser.add_argument(
        "url",
        help="Public page to fetch. Must start with http:// or https://.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check configuration and print the request. Do not contact Bright Data.",
    )
    parser.add_argument(
        "--confirm-request",
        action="store_true",
        help="Send exactly one real request. This can use Bright Data credits.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        target_url = validate_target_url(args.url)
        api_key, zone = load_credentials()
        if args.dry_run:
            print(describe_dry_run(zone, target_url, args.confirm_request))
            return 0
        if not args.confirm_request:
            print(
                "Refusing to contact Bright Data.\n"
                "A real request is sent only when you pass --confirm-request.\n"
                "That request can use Bright Data credits, and this script will not retry it.\n"
                "To check configuration without sending anything, pass --dry-run instead.",
                file=sys.stderr,
            )
            return 2
        print(
            f"Sending one Bright Data request for {target_url}.",
            file=sys.stderr,
        )
        html = fetch_html(target_url, api_key, zone)
        output_path = save_html(target_url, html)
    except ScrapeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: Could not save the HTML response: {exc}", file=sys.stderr)
        return 1

    print(f"HTML saved to {output_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

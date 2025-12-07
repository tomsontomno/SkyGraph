# SkyGraph

**SkyGraph** is a powerful, asynchronous flight data analysis tool designed to build and explore complex flight networks. It fetches real-time flight data, constructs a directed graph of routes, and finds optimal travel paths based on your custom criteria—perfect for digital nomads and frequent flyers looking for multi-city trips.

## Features

- **Asynchronous Data Fetching**: Rapidly scrapes flight data using `aiohttp` and smart proxy rotation.
- **Graph-Based Routing**: Builds a directed graph of all available flights to find complex, multi-leg routes.
- **Customizable Search**: Filter routes by time gaps, number of flights, and specific city/country preferences.
- **Smart Transfer Logic**: Automatically calculates self-transfer times between airports, including ground transport estimates.
- **Visual & Audio Feedback**: Real-time progress logging and success notifications.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone https://github.com/yourusername/SkyGraph.git
    cd SkyGraph
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up configuration**:
    - Copy the example templates to the `data/current/` directory:
      ```bash
      mkdir -p data/current
      cp data/templates/curl_request_data.json.example data/current/curl_request_data.json
      cp data/templates/preferences.json.example data/current/preferences.json
      ```
    - **Important**: You must populate `curl_request_data.json` with valid headers and cookies from a recent browser session to `wizzair.com`.

4.  **Environment Variables**:
    Create a `.env` file in the root directory with your proxy settings (optional but recommended for heavy scraping):
    ```env
    WEBSHARE_API_TOKEN=your_token
    WEBSHARE_PROXIES_URL=your_proxy_list_url
    ```

## Usage

### 1. Fetch Flight Data
Run the main script to start fetching flight data and building the graph.
```bash
python main.py
```
This will:
- Update proxies (if configured).
- Scrape flight data for the configured days.
- Build a flight graph and save it to `data/current/graph.pkl`.

### 2. Find Routes
Use the route finder to query the built graph for optimal trips.
```bash
python core/route_find.py
```
*Note: Ensure `data/current/settings.json` is configured with your desired search parameters (e.g., origin cities, max flights, time gaps).*

## Architecture

- **`core/fetcher_optimize.py`**: The engine room. Handles async requests, proxy management, and graph construction.
- **`core/route_find.py`**: The navigator. Implements DFS algorithms to find valid routes within the flight graph.
- **`core/proxy_manager.py`**: Handles proxy rotation and rate limiting.
- **`data/`**: Stores all configuration, templates, and runtime data (graphs, logs).

## Disclaimer

This tool is for educational purposes only. Use responsibly and respect the terms of service of any websites you interact with.

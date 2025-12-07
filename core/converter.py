import json
import networkx as nx
import pickle
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# Define project paths
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "current"
GRAPH_DIR = PROJECT_ROOT / "flight_graph"


def load_json_file(file_path: Path):
    """
    Loads the JSON file from the given path.

    Args:
        file_path (Path): Path to the JSON file.

    Returns:
        dict: The loaded JSON data.
    """
    logger.info(f"Loading JSON file from {file_path}")
    with file_path.open('r', encoding='utf-8') as f:
        return json.load(f)


def create_directed_graph_from_json(flight_data):
    """
    Converts the flight data in JSON format into a directed graph.

    Args:
        flight_data (dict): The flight data in JSON format.

    Returns:
        networkx.DiGraph: The constructed directed graph.
    """
    logger.info("Creating directed graph from JSON data")
    graph = nx.DiGraph()

    for origin, destinations in flight_data.items():
        for destination, flights in destinations.items():
            if not graph.has_edge(origin, destination):
                graph.add_edge(origin, destination, flights=[])

            for flight in flights:
                departure_time = flight[0]
                arrival_time = flight[1]
                graph[origin][destination]['flights'].append([departure_time, arrival_time])

    return graph


def save_graph_to_pickle(graph, file_path: Path):
    """
    Saves the directed graph to a .pkl file.

    Args:
        graph (networkx.DiGraph): The directed graph to be saved.
        file_path (Path): The file path to save the graph under.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open('wb') as f:
        pickle.dump(graph, f)
    logger.info(f"Graph saved to {file_path}")


def convert_json_to_graph_and_save(json_file_path: Path, output_file_path: Path):
    """
    Converts the flight JSON file into a directed graph and saves it as a .pkl file.

    Args:
        json_file_path (Path): Path to the JSON file with flight data.
        output_file_path (Path): Path where the .pkl file will be saved.
    """
    flight_data = load_json_file(json_file_path)
    graph = create_directed_graph_from_json(flight_data)
    save_graph_to_pickle(graph, output_file_path)


def convert(filename=None):
    if filename is None:
        filename = input("Filename in flight_graph folder: ")
    json_file_path = GRAPH_DIR / filename
    output_file_path = DATA_DIR / "graph.pkl"
    convert_json_to_graph_and_save(json_file_path, output_file_path)


def main():
    convert()


if __name__ == "__main__":
    main()

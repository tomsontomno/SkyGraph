import json
import networkx as nx
import pickle


def load_json_file(file_path):
    """
    Loads the JSON file from the given path.

    Args:
        file_path (str): Path to the JSON file.

    Returns:
        dict: The loaded JSON data.
    """
    with open(file_path, 'r') as f:
        return json.load(f)


def create_directed_graph_from_json(flight_data):
    """
    Converts the flight data in JSON format into a directed graph.

    Args:
        flight_data (dict): The flight data in JSON format.

    Returns:
        networkx.DiGraph: The constructed directed graph.
    """
    graph = nx.DiGraph()

    for origin, destinations in flight_data.items():
        for destination, flights in destinations.items():
            # Ensure there is an edge with a 'flights' attribute
            if not graph.has_edge(origin, destination):
                graph.add_edge(origin, destination, flights=[])

            # Add each flight's departure and arrival times as a list
            for flight in flights:
                departure_time = flight[0]  # First element is the departure time
                arrival_time = flight[1]  # Second element is the arrival time
                # Append the flight (departure and arrival) to the 'flights' attribute
                graph[origin][destination]['flights'].append([departure_time, arrival_time])

    return graph


def save_graph_to_pickle(graph, filename):
    """
    Saves the directed graph to a .pkl file.

    Args:
        graph (networkx.DiGraph): The directed graph to be saved.
        filename (str): The filename to save the graph under.
    """
    with open(filename, 'wb') as f:
        pickle.dump(graph, f)
    print(f"Graph saved to {filename}")


def convert_json_to_graph_and_save(json_file_path, output_file_path):
    """
    Converts the flight JSON file into a directed graph and saves it as a .pkl file.

    Args:
        json_file_path (str): Path to the JSON file with flight data.
        output_file_path (str): Path where the .pkl file will be saved.
    """
    # Load the flight data from JSON file
    flight_data = load_json_file(json_file_path)

    # Create a directed graph from the flight data
    graph = create_directed_graph_from_json(flight_data)

    # Save the directed graph as a .pkl file
    save_graph_to_pickle(graph, output_file_path)


# Usage example:
if __name__ == "__main__":
    json_file_path = './flight_graph/' + str(input("filename Graph:\n"))  # Path to your JSON file
    output_file_path = 'graph.pkl'  # Path where the graph will be saved

    # Convert the JSON to a directed graph and save it
    convert_json_to_graph_and_save(json_file_path, output_file_path)

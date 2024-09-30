import re
import httpx
import networkx as nx
import numpy as np
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.logger import logger
import logging
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
import uvicorn
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import ssl
import certifi

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Allow requests from your frontend at http://localhost:3000
origins = [
    "http://localhost:3000",  # Adjust this to match your frontend URL
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allow requests from specific origin
    allow_credentials=True,  # Allow cookies to be sent with the request
    allow_methods=["*"],  # Allow all methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allow all headers (e.g., content-type)
)

class UsernameRequest(BaseModel):
    usernames: str


def parse_usernames(usernames: str) -> list[str]:
    return [username.strip() for username in re.split(r'[,\s]+', usernames) if username.strip()]

def get_user_fids(usernames: list[str]) -> dict[str, tuple[int, int]]:
    user_fids = {}
    with httpx.Client() as client:
        for username in usernames:
            response = client.get(f"https://fnames.farcaster.xyz/transfers/current?name={username}")
            if response.status_code == 200:
                user_data = response.json()
                fid = user_data['transfer']['to']
                timestamp = user_data['transfer']['timestamp']  # Unix timestamp in seconds
                user_fids[username] = (fid, timestamp)
            else:
                logger.error(f"Failed to retrieve FID for username: {username}. Status code: {response.status_code}")
    return user_fids

def get_user_data(user_fids: dict[str, tuple[int, int]]) -> list[dict]:
    user_data_list = []
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    with httpx.Client(verify=ssl_context) as client:
        for username, (fid, timestamp) in user_fids.items():
            # Call API to get user avatar
            avatar_response = client.get(f"https://hub.farcaster.standardcrypto.vc:2281/v1/userDataByFid?fid={fid}&user_data_type=USER_DATA_TYPE_PFP")
            avatar_url = None
            if avatar_response.status_code == 200:
                avatar_data = avatar_response.json()
                avatar_url = avatar_data['data']['userDataBody']['value']
            else:
                logger.error(f"Failed to retrieve avatar for username: {username}. Status code: {avatar_response.status_code}")
            
            user_data_list.append({
                'username': username,
                'fid': fid,
                'avatar_url': avatar_url,
                'timestamp': timestamp
            })
    
    return user_data_list

def get_user_follow_info(user_fids: dict[str, int]) -> list[dict]:
    follow_info_list = []
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    with httpx.Client(verify=ssl_context) as client:
        for username, fid in user_fids.items():
            url = f"https://hub.farcaster.standardcrypto.vc:2281/v1/linksByFid?fid={fid}"
            try:
                response = client.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()
                follow_info = {
                    'username': username,
                    'fid': fid,
                    'following': []
                }
                for message in data['messages']:
                    if message['data']['type'] == 'MESSAGE_TYPE_LINK_ADD' and message['data']['linkBody']['type'] == 'follow':
                        # Farcaster epoch is 2021-01-01 00:00:00 UTC
                        # timestamp is in seconds
                        timestamp = int(message['data']['timestamp']) + 1609459200
                        follow_info['following'].append({
                            'timestamp': timestamp,
                            'targetFid': message['data']['linkBody']['targetFid']
                        })
                follow_info_list.append(follow_info)
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error for username: {username}, FID: {fid}. Status code: {e.response.status_code}")
                logger.error(f"Response content: {e.response.text}")
            except httpx.RequestError as e:
                logger.error(f"Request error for username: {username}, FID: {fid}: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error for username: {username}, FID: {fid}: {str(e)}")
    
    return follow_info_list

def create_graph(follow_info, user_data):
    G = nx.DiGraph()
    
    for user in user_data:
        username = user['username']
        fid = user['fid']
        G.add_node(fid, username=username, timestamp=user['timestamp'], avatar_url=user['avatar_url'])
    
    for user in follow_info:
        fid = user['fid']
        for follow in user['following']:
            target_fid = follow['targetFid']
            
            # Only add edges between the specified users
            if target_fid in [u['fid'] for u in user_data]:
                # Use the follow timestamp instead of the source node timestamp
                timestamp = follow['timestamp']
                G.add_edge(fid, target_fid, timestamp=timestamp)
    
    return G

def calculate_graph_metrics(graph: nx.DiGraph, start_time: int, end_time: int, user_fids: set[int]):
    logger.info("Calculating graph metrics")
    logger.info(f"Start time (Unix): {start_time}")
    logger.info(f"End time (Unix): {end_time}")

    # Filter edges
    filtered_edges = [
        (u, v, d) for (u, v, d) in graph.edges(data=True)
        if start_time <= d['timestamp'] <= end_time and u in user_fids and v in user_fids
    ]

    # Create filtered graph
    filtered_graph = nx.DiGraph()
    filtered_graph.add_nodes_from((n, graph.nodes[n]) for n in graph.nodes() if n in user_fids)
    filtered_graph.add_edges_from(filtered_edges)

    logger.info(f"Filtered graph has {filtered_graph.number_of_nodes()} nodes and {filtered_graph.number_of_edges()} edges")

    if filtered_graph.number_of_nodes() == 0 or filtered_graph.number_of_edges() == 0:
        logger.warning("Filtered graph is empty. Check your time range and data.")
        return {
            'num_nodes': 0,
            'num_edges': 0,
            'density': 0,
            'avg_clustering': 0,
            'adjacency_matrix': np.array([]),
            'shortest_path_matrix': np.array([]),
            'node_metrics': {}
        }

    # Node list for consistent ordering
    node_list = sorted(filtered_graph.nodes())

    # Compute adjacency matrix
    adj_matrix = nx.to_numpy_array(filtered_graph, nodelist=node_list)

    # Compute all-pairs shortest path lengths
    lengths = dict(nx.all_pairs_shortest_path_length(filtered_graph))
    num_nodes = len(node_list)
    shortest_path_matrix = np.full((num_nodes, num_nodes), np.inf)

    node_indices = {node: idx for idx, node in enumerate(node_list)}
    for source in lengths:
        for target, length in lengths[source].items():
            i = node_indices[source]
            j = node_indices[target]
            shortest_path_matrix[i, j] = length

    # Replace infinities with None for JSON serialization
    shortest_path_matrix = np.where(np.isinf(shortest_path_matrix), None, shortest_path_matrix)

    # Compute additional metrics
    num_edges = filtered_graph.number_of_edges()
    density = nx.density(filtered_graph)

    # Clustering requires undirected graph
    undirected_graph = filtered_graph.to_undirected()
    avg_clustering = nx.average_clustering(undirected_graph)
    node_clustering = nx.clustering(undirected_graph)

    # Degrees
    degrees = dict(filtered_graph.degree())
    in_degrees = dict(filtered_graph.in_degree())
    out_degrees = dict(filtered_graph.out_degree())

    # Betweenness centrality
    betweenness = nx.betweenness_centrality(filtered_graph)

    # Node metrics
    node_metrics = {}
    for node in node_list:
        node_metrics[node] = {
            'degree': degrees.get(node, 0),
            'in_degree': in_degrees.get(node, 0),
            'out_degree': out_degrees.get(node, 0),
            'clustering_coefficient': node_clustering.get(node, 0),
            'betweenness_centrality': betweenness.get(node, 0),
        }

    return {
        'num_nodes': filtered_graph.number_of_nodes(),
        'num_edges': num_edges,
        'density': density,
        'avg_clustering': avg_clustering,
        'adjacency_matrix': adj_matrix,
        'shortest_path_matrix': shortest_path_matrix,
        'node_metrics': node_metrics
    }

def graph_to_json(G, user_fid_set):
    nodes = [
        {
            'id': node,
            'username': G.nodes[node].get('username', ''),
            'timestamp': G.nodes[node].get('timestamp', None),
            'avatar_url': G.nodes[node].get('avatar_url', None)
        } for node in G.nodes() if node in user_fid_set
    ]
    
    links = [
        {
            'source': u,
            'target': v,
            'timestamp': data['timestamp']
        } for u, v, data in G.edges(data=True) if u in user_fid_set and v in user_fid_set
    ]    
    # Log node information
    logger.info(f"Nodes being sent to frontend:")
    for node in nodes:
        logger.info(f"  ID: {node['id']}, Username: {node['username']}, Timestamp: {node['timestamp']}, Avatar URL: {node['avatar_url']}")

    # Log link information
    logger.info(f"Links being sent to frontend:")
    for link in links:
        logger.info(f"  Source: {link['source']}, Target: {link['target']}, Timestamp: {link['timestamp']}")
    
    logger.info(f"Total number of nodes: {len(nodes)}")
    logger.info(f"Total number of links: {len(links)}")
    
    return {'nodes': nodes, 'links': links}

@app.post("/api/graph_data")
async def get_graph_data(request: UsernameRequest):
    try:
        usernames = request.usernames   
        logger.info(f"Received usernames: {usernames}")
        parsed_usernames = parse_usernames(usernames)
        
        user_fids = get_user_fids(parsed_usernames)
        user_fid_set = set(fid for _, (fid, _) in user_fids.items())
        
        user_data = get_user_data(user_fids)
        logger.info(f"User data: {user_data}")
        
        follow_info = get_user_follow_info({username: fid for username, (fid, _) in user_fids.items()})
        logger.info(f"Follow info: {follow_info}")
        
        graph = create_graph(follow_info, user_data)
        logger.info(f"Graph created with {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges")
        
        # Calculate start and end timestamps
        all_timestamps = [
            d['timestamp'] for u, v, d in graph.edges(data=True) 
            if u in user_fid_set and v in user_fid_set
        ] + [graph.nodes[n]['timestamp'] for n in graph.nodes() if n in user_fid_set]

        start_time = min(all_timestamps) if all_timestamps else 0
        end_time = max(all_timestamps) if all_timestamps else 0

        logger.info(f"Start time: {start_time}")
        logger.info(f"End time: {end_time}")
        
        graph_metrics = calculate_graph_metrics(graph, start_time, end_time, user_fid_set)
        graph_json = graph_to_json(graph, user_fid_set)

        return {
            "graph_metrics": {
                "num_nodes": graph_metrics['num_nodes'],
                "num_edges": graph_metrics['num_edges'],
                "density": graph_metrics['density'],
                "avg_clustering": graph_metrics['avg_clustering'],
                "adjacency_matrix": graph_metrics['adjacency_matrix'].tolist(),
                "shortest_path_matrix": graph_metrics['shortest_path_matrix'].tolist(),
                "node_metrics": graph_metrics['node_metrics']
            },
            "graph_structure": graph_json,
            "timestamps": all_timestamps,
            "start_time": start_time,
            "end_time": end_time
        }
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        return {"error": str(e)}

# Serve static files (HTML, CSS, JS)
# app.mount("/static", StaticFiles(directory="static"), name="static")

# @app.get("/")
# async def read_index():
#     return FileResponse("static/index.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
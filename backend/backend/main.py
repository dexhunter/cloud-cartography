import re
import httpx
import networkx as nx
import numpy as np
from datetime import datetime
from fastapi import FastAPI
from fastapi.logger import logger
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
import uvicorn

app = FastAPI()

def parse_usernames(usernames: str) -> list[str]:
    return [username.strip() for username in re.split(r'[,\s]+', usernames) if username.strip()]

def get_user_fids(usernames: list[str]) -> dict[str, int]:
    user_fids = {}
    with httpx.Client() as client:
        for username in usernames:
            response = client.get(f"https://fnames.farcaster.xyz/transfers/current?name={username}")
            if response.status_code == 200:
                user_data = response.json()
                fid = user_data['transfer']['to']
                user_fids[username] = fid
            else:
                logger.error(f"Failed to retrieve FID for username: {username}. Status code: {response.status_code}")
    return user_fids

def get_user_data(user_fids: dict[str, int]) -> list[dict]:
    user_data_list = []
    with httpx.Client() as client:
        for username, fid in user_fids.items():
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
                'avatar_url': avatar_url
            })
    
    return user_data_list

def get_user_follow_info(user_fids: dict[str, int]) -> list[dict]:
    follow_info_list = []
    with httpx.Client() as client:
        for username, fid in user_fids.items():
            response = client.get(f"https://hub.farcaster.standardcrypto.vc:2281/v1/linksByFid?fid={fid}")
            if response.status_code == 200:
                data = response.json()
                follow_info = {
                    'username': username,
                    'fid': fid,
                    'following': []
                }
                for message in data['messages']:
                    if message['data']['type'] == 'MESSAGE_TYPE_LINK_ADD' and message['data']['linkBody']['type'] == 'follow':
                        follow_info['following'].append({
                            'timestamp': message['data']['timestamp'],
                            'targetFid': message['data']['linkBody']['targetFid']
                        })
                follow_info_list.append(follow_info)
            else:
                logger.error(f"Failed to retrieve follow info for username: {username}. Status code: {response.status_code}")
    
    return follow_info_list

def create_graph(follow_info):
    G = nx.DiGraph()
    
    for user in follow_info:
        username = user['username']
        fid = user['fid']
        G.add_node(fid, username=username)
        
        for follow in user['following']:
            target_fid = follow['targetFid']
            timestamp = follow['timestamp']
            
            # Add the target node if it doesn't exist
            if not G.has_node(target_fid):
                G.add_node(target_fid)
            
            # Add an edge from the user to the target
            G.add_edge(fid, target_fid, timestamp=timestamp)
    
    logger.info(f"Created graph with {G.number_of_nodes()} nodes and {G.number_of_edges()} edges")
    return G

def calculate_graph_metrics(graph: nx.MultiDiGraph, start_time: datetime, end_time: datetime):
    filtered_graph = graph.edge_subgraph([
        (u, v) for (u, v, d) in graph.edges(data=True)
        if start_time <= d.get('timestamp', 0) <= end_time
    ])
    
    logger.info(f"Filtered graph has {filtered_graph.number_of_nodes()} nodes and {filtered_graph.number_of_edges()} edges")
    
    if filtered_graph.number_of_nodes() == 0 or filtered_graph.number_of_edges() == 0:
        logger.warning("Filtered graph is empty. Check your time range and data.")
        return None  # or return some default metrics
    
    adj_matrix = nx.adjacency_matrix(filtered_graph).todense()
    
    # All-pairs shortest path matrix
    # Note: This can be computationally expensive for large graphs
    shortest_paths = dict(nx.all_pairs_shortest_path_length(filtered_graph))
    num_nodes = filtered_graph.number_of_nodes()
    shortest_path_matrix = np.full((num_nodes, num_nodes), np.inf)
    
    node_list = list(filtered_graph.nodes())
    for i, source in enumerate(node_list):
        for j, target in enumerate(node_list):
            if source in shortest_paths and target in shortest_paths[source]:
                shortest_path_matrix[i, j] = shortest_paths[source][target]
    
    return {
        'num_edges': filtered_graph.number_of_edges(),
        'adjacency_matrix': adj_matrix,
        'shortest_path_matrix': shortest_path_matrix
    }

@app.get("/api/graph_data")
async def get_graph_data(start_time: int, end_time: int):
    # Assuming you have a way to get or store the full graph data
    full_graph = create_graph(get_user_follow_info(get_user_fids(parse_usernames("balajis,dexhunter,feides"))))
    
    metrics = calculate_graph_metrics(full_graph, datetime.fromtimestamp(start_time), datetime.fromtimestamp(end_time))
    
    if metrics is None:
        return {"error": "No data available for the specified time range"}
    
    return {
        "nodes": [{"id": node, "username": data.get("username", "")} for node, data in full_graph.nodes(data=True)],
        "links": [{"source": u, "target": v, "timestamp": d["timestamp"]} for u, v, d in full_graph.edges(data=True)],
        "metrics": {
            "num_edges": metrics["num_edges"],
            "adjacency_matrix": json.dumps(metrics["adjacency_matrix"].tolist()),
            "shortest_path_matrix": json.dumps(metrics["shortest_path_matrix"].tolist())
        }
    }

# Serve static files (HTML, CSS, JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

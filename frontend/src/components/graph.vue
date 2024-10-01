<template>
  <v-card class="pa-4 ma-4" elevation="2">
    <!-- User Input Form -->
    <v-form @submit.prevent="submitUsernames">
      <v-text-field
        v-model="userInput"
        label="Enter usernames"
        outlined
        @keyup.enter="submitUsernames"
      />
      <v-btn
        color="primary"
        type="submit"
        class="mt-2"
      >
        Enter
      </v-btn>
    </v-form>

    <!-- Real-time Backend Logs -->
    <v-card v-if="isConnected" class="mt-4 mb-4 pa-4" outlined>
      <h3>Real-time Backend Logs</h3>
      <v-btn @click="backendLogs = []" color="secondary" small class="mb-2">
        Clear Logs
      </v-btn>
      <div class="log-container">
        <pre v-for="(log, index) in backendLogs" :key="index">{{ log }}</pre>
      </div>
    </v-card>

    <!-- Time Slider -->
    <v-slider
      v-if="timestamps.length > 0"
      v-model="selectedTimeIndex"
      :min="0"
      :max="timestamps.length - 1"
      :step="1"
      label="Select Time"
      :ticks="true"
      tick-size="4"
      class="my-4"
    >
      <template v-slot:append>
        <span>{{ formatDate(timestamps[selectedTimeIndex]) }}</span>
      </template>
    </v-slider>

    <!-- Graph Container -->
    <div ref="graphContainer" class="graph-container"></div>

    <!-- Heatmap Container -->
    <div ref="heatmapContainer" class="heatmap-container"></div>

    <!-- Graph Metrics -->
    <v-card v-if="metrics" class="ma-4 pa-4" outlined>
      <h4>Graph Metrics</h4>
      <p><strong>Number of Nodes:</strong> {{ metrics.num_nodes }}</p>
      <p><strong>Number of Edges:</strong> {{ metrics.num_edges }}</p>
      <p><strong>Density:</strong> {{ metrics.density }}</p>
      <p><strong>Average Clustering Coefficient:</strong> {{ metrics.avg_clustering }}</p>

      <!-- Optional: Display Node Metrics if needed -->
      <div v-if="metrics.node_metrics">
        <h5>Node Metrics</h5>
        <ul>
          <li v-for="(value, key) in metrics.node_metrics" :key="key">
            <strong>{{ key }}:</strong> {{ value }}
          </li>
        </ul>
      </div>

      <!-- Adjusted: Display adjacency and shortest path matrices -->
      <div v-if="metrics.adjacency_matrix">
        <h5>Adjacency Matrix:</h5>
        <pre>{{ formatMatrix(metrics.adjacency_matrix) }}</pre>
      </div>
      <div v-if="metrics.shortest_path_matrix">
        <h5>Shortest Path Matrix:</h5>
        <pre>{{ formatMatrix(metrics.shortest_path_matrix) }}</pre>
      </div>

      <p><strong>Start Time:</strong> {{ formatDate(timestamps[0]) }}</p>
      <p><strong>End Time:</strong> {{ formatDate(timestamps[timestamps.length - 1]) }}</p>
    </v-card>
  </v-card>
</template>

<script>
import * as d3 from 'd3';
// Import additional D3 modules if needed

export default {
  data() {
    return {
      userInput: '',
      graphData: null,
      metrics: null,
      timestamps: [],
      selectedTimeIndex: 0,
      socket: null,
      backendLogs: [],
      isConnected: false,
    };
  },
  watch: {
    selectedTimeIndex(newVal, oldVal) {
      console.log(`selectedTimeIndex changed from ${oldVal} to ${newVal}`);
      this.updateGraph();
    }
  },
  methods: {
    async submitUsernames() {
      console.log('Submitting usernames:', this.userInput);
      this.backendLogs = []; // Clear previous logs

      try {
        // Use a relative URL instead of an absolute one
        const response = await fetch("/api/graph_data", {
          method: "POST",
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ usernames: this.userInput })
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (data.error) {
          console.error(data.error);
        } else {
          this.graphData = data.graph_structure;
          this.metrics = data.graph_metrics;
          this.timestamps = data.timestamps.sort((a, b) => a - b);

          this.selectedTimeIndex = 0;
          this.updateGraph();
        }
      } catch (error) {
        console.error("Error fetching graph data:", error);
      }
    },
    updateGraph() {
      if (!this.graphData || !this.graphData.links) {
        console.error("Graph data is undefined");
        return;
      }
      const currentTime = this.timestamps[this.selectedTimeIndex];
      console.log("Current Time:", currentTime);

      // Debug: Log node timestamps
      this.graphData.nodes.forEach(node => {
        console.log(`Node ${node.id} Timestamp:`, node.timestamp);
      });

      // Debug: Log link timestamps
      this.graphData.links.forEach(link => {
        console.log(`Link from ${link.source} to ${link.target} Timestamp:`, link.timestamp);
      });

      // Filter nodes based on current time
      const filteredNodes = this.graphData.nodes.filter(node => node.timestamp <= currentTime);
      console.log("Filtered Nodes:", filteredNodes);

      // Get node IDs from filtered nodes
      const nodeIds = new Set(filteredNodes.map(node => node.id));

      // Filter links based on current time and if both source and target nodes exist
      const filteredLinks = this.graphData.links.filter(link =>
        link.timestamp <= currentTime && nodeIds.has(link.source) && nodeIds.has(link.target)
      );
      console.log("Filtered Links:", filteredLinks);

      // Proceed with rendering the graph
      this.filteredGraph = {
        nodes: filteredNodes,
        links: filteredLinks.map(link => ({
          ...link,
          source: link.source.id || link.source,
          target: link.target.id || link.target,
        })),
      };

      this.renderGraph(this.filteredGraph);

      // Render the heatmap using the adjacency matrix from the metrics
      if (this.metrics.adjacency_matrix) {
        this.renderHeatmap(this.metrics.adjacency_matrix);
      }
    },
    renderGraph(graph) {
      const container = this.$refs.graphContainer;
      d3.select(container).selectAll("*").remove();

      const width = container.clientWidth || 600;
      const height = container.clientHeight || 600;

      const svg = d3.select(container).append("svg")
        .attr("width", width)
        .attr("height", height);

      const link = svg.append("g")
        .attr("class", "links")
        .selectAll("line")
        .data(graph.links)
        .enter().append("line")
        .attr("stroke-width", 1)
        .attr("stroke", "#999");

      const node = svg.append("g")
        .attr("class", "nodes")
        .selectAll("g")
        .data(graph.nodes)
        .enter().append("g")
        .call(d3.drag()
          .on("start", dragstarted)
          .on("drag", dragged)
          .on("end", dragended));

      node.append("circle")
        .attr("r", 20)
        .attr("fill", "white")
        .attr("stroke", "blue")
        .attr("stroke-width", 2);

      node.append("image")
        .attr("xlink:href", d => d.avatar_url)
        .attr("x", -18)
        .attr("y", -18)
        .attr("width", 36)
        .attr("height", 36)
        .attr("clip-path", "circle(18px at center)");

      node.append("text")
        .attr("dy", 30)
        .attr("text-anchor", "middle")
        .attr("fill", "white")  // Set text color to white
        .text(d => d.username);

      // Force simulation for layout
      const simulation = d3.forceSimulation(graph.nodes)
        .force("link", d3.forceLink(graph.links).id(d => d.id).distance(100))
        .force("charge", d3.forceManyBody().strength(-300))
        .force("center", d3.forceCenter(width / 2, height / 2))
        .on("tick", ticked);

      function ticked() {
        link
          .attr("x1", d => d.source.x)
          .attr("y1", d => d.source.y)
          .attr("x2", d => d.target.x)
          .attr("y2", d => d.target.y);

        node
          .attr("transform", d => `translate(${d.x},${d.y})`);
      }

      function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      }

      function dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
      }

      function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      }
    },
    formatDate(timestamp) {
      if (!timestamp) return '';
      // Adjust based on your timestamp format (seconds or milliseconds)
      const date = new Date(timestamp * 1000); // If timestamps are in seconds
      return date.toLocaleString();
    },
    renderHeatmap(matrix) {
      const container = this.$refs.heatmapContainer;
      d3.select(container).selectAll("*").remove();

      const data = [];
      const size = matrix.length;

      // Prepare data in the format [{ x: 0, y: 0, value: 1 }, ...]
      for (let i = 0; i < size; i++) {
        for (let j = 0; j < size; j++) {
          data.push({ x: j, y: i, value: matrix[i][j] });
        }
      }

      const margin = { top: 50, right: 0, bottom: 100, left: 100 },
        width = 500 - margin.left - margin.right,
        height = 500 - margin.top - margin.bottom;

      const svg = d3.select(container)
        .append("svg")
        .attr("width", width + margin.left + margin.right)
        .attr("height", height + margin.top + margin.bottom)
        .append("g")
        .attr("transform", `translate(${margin.left},${margin.top})`);

      const xElements = d3.range(size);
      const yElements = d3.range(size);

      const xScale = d3.scaleBand()
        .domain(xElements)
        .range([0, width]);

      const yScale = d3.scaleBand()
        .domain(yElements)
        .range([0, height]);

      const colorScale = d3.scaleSequential()
        .interpolator(d3.interpolateBlues)
        .domain([0, 1]); // Adjust domain based on your data

      svg.selectAll()
        .data(data, function(d) { return d.x + ':' + d.y; })
        .enter()
        .append("rect")
        .attr("x", (d) => xScale(d.x))
        .attr("y", (d) => yScale(d.y))
        .attr("width", xScale.bandwidth())
        .attr("height", yScale.bandwidth())
        .style("fill", (d) => colorScale(d.value));

      // Add labels
      const nodeNames = this.filteredGraph.nodes.map(node => node.username);

      const xAxis = d3.axisBottom(xScale)
        .tickFormat((d) => nodeNames[d]);

      const yAxis = d3.axisLeft(yScale)
        .tickFormat((d) => nodeNames[d]);

      svg.append("g")
        .attr("transform", `translate(0,${height})`)
        .call(xAxis)
        .selectAll("text")	
        .style("text-anchor", "end")
        .attr("dx", "-.8em")
        .attr("dy", ".15em")
        .attr("transform", "rotate(-65)");

      svg.append("g")
        .call(yAxis);
    },
    formatMatrix(matrix) {
      if (!matrix) return '';
      return matrix.map(row => row.join(' ')).join('\n');
    },
    connectWebSocket() {
      console.log('Attempting to connect to WebSocket...');
      this.socket = new WebSocket('ws://localhost:8000/ws/logs');
      
      this.socket.onopen = () => {
        console.log('WebSocket connected successfully');
        this.isConnected = true;
      };
      
      this.socket.onmessage = (event) => {
        console.log('Received message:', event.data);
        this.backendLogs.push(event.data);
        // Optionally, limit the number of logs displayed
        if (this.backendLogs.length > 100) {
          this.backendLogs.shift();
        }
      };
      
      this.socket.onclose = (event) => {
        console.log('WebSocket disconnected:', event);
        this.isConnected = false;
      };
      
      this.socket.onerror = (error) => {
        console.error('WebSocket error:', error);
      };
    },

    disconnectWebSocket() {
      if (this.socket) {
        this.socket.close();
      }
    },
  },
  mounted() {
    this.connectWebSocket();
  },

  beforeUnmount() {
    this.disconnectWebSocket();
  },
};
</script>

<style scoped>
.graph-container {
  width: 100%;
  height: 600px;
  border: 1px solid #ccc;
  margin-top: 20px;
  background-color: #2c3e50;
  overflow: hidden;
}

/* New styles for heatmap */
.heatmap-container {
  width: 100%;
  max-width: 800px;
  margin: 20px auto;
}

.log-container {
  max-height: 200px; /* Adjust the height as needed */
  overflow-y: auto;
  background-color: #000; /* Black background */
  color: #fff; /* White font color */
  padding: 10px;
  border-radius: 4px;
}

.log-container pre {
  margin: 0;
  padding: 2px 0;
  font-size: 14px;
  white-space: pre-wrap;
  word-wrap: break-word;
  color: #fff; /* Ensure font color is white */
}
</style>
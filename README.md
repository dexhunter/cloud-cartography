# cloud cartography

[demo page](https://cloud-cartography.replit.app/)

## feature

* social network visualization
* metrics calculation
* real-time backend logs

## development logs

* tried bokeh, pyvis but doesn't seem ideal to create graph, decide move back to separate backend and frontend, and using d3js for easy to display
* with public apis, need to use asynchrous methods to call to make it faster
* display loggers for debugging
* also need to convert timestamp from the Farcaster Epoch, which began on Jan 1, 2021 00:00:00 UTC (In seconds: 1609459200)
* for deploying on replit, will need to use relative url for fetching data and I build the frontend files to easier serving


let experimentData = [];

let dashPlayer = window.player;

let metricInterval = setInterval(() => {
  if (!dashPlayer) {
    console.log("Player not found.");
    return;
  }

  let dashMetrics = dashPlayer.getDashMetrics();

  // 1. Buffer level (second)
  let bufferLevel = dashPlayer.getBufferLength("video");

  // 2. Measured throughput (Mbps)
  // dash.js returns kbps, so we divide by 1000 to get Mbps
  let throughputMbps = dashPlayer.getAverageThroughput("video") / 1000;

  // 3. Latency (average over the four last requested segments)
  let requests = dashMetrics.getHttpRequests("video");
  // Get the last 4 requests
  let last4Requests = requests.slice(-4);
  let totalLatency = 0;
  let validRequests = 0;

  last4Requests.forEach((req) => {
    if (req.tresponse && req.trequest) {
      totalLatency += req.tresponse.getTime() - req.trequest.getTime();
      validRequests++;
    }
  });

  let avgLatency = validRequests > 0 ? totalLatency / validRequests : 0;

  // Save the snapshot
  let currentMetrics = {
    timestamp: new Date().toLocaleTimeString(),
    bufferLevel_s: bufferLevel.toFixed(2),
    throughput_Mbps: throughputMbps.toFixed(2),
    latency_ms: avgLatency.toFixed(2),
  };

  experimentData.push(currentMetrics);
  console.log("Recorded at 8s mark:", currentMetrics);
}, 8000);

function downloadMetrics() {
  console.table(experimentData);
  clearInterval(metricInterval);
}

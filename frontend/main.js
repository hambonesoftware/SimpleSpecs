const healthStatus = document.createElement("pre");
healthStatus.textContent = "Checking backend health...";
document.querySelector("main")?.append(healthStatus);

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      throw new Error(`Unexpected status ${response.status}`);
    }
    const payload = await response.json();
    healthStatus.textContent = JSON.stringify(payload, null, 2);
  } catch (error) {
    console.error(error);
    healthStatus.textContent = "Health check failed. See console for details.";
  }
}

checkHealth();

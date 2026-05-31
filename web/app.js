const form = document.querySelector("#tool-form");
const fileInput = document.querySelector("#image");
const fileLabel = document.querySelector("#file-label");
const preview = document.querySelector("#source-preview");
const sourceMeta = document.querySelector("#source-meta");
const ratioSelect = document.querySelector("#ratio-select");
const customRatioField = document.querySelector("#custom-ratio-field");
const customRatio = document.querySelector("#custom-ratio");
const canvasOptions = document.querySelector("#canvas-options");
const chunkOptions = document.querySelector("#chunk-options");
const chunkCount = document.querySelector("#chunk-count");
const carouselPadding = document.querySelector("#carousel-padding");
const colorField = document.querySelector("#color-field");
const backgroundColor = document.querySelector("#background-color");
const outputFormat = document.querySelector("#output-format");
const statusText = document.querySelector("#status");
const resultGrid = document.querySelector("#result-grid");
const downloadAll = document.querySelector("#download-all");
const expiry = document.querySelector("#expiry");

let sourceWidth = null;
let sourceHeight = null;

function selectedValue(name) {
  return document.querySelector(`input[name="${name}"]:checked`).value;
}

function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.classList.toggle("error", isError);
}

function syncOptions() {
  const mode = selectedValue("mode");
  const bgMode = selectedValue("background_mode");
  canvasOptions.hidden = mode !== "canvas";
  chunkOptions.hidden = mode !== "chunks";
  customRatioField.hidden = ratioSelect.value !== "custom" || mode !== "canvas";
  colorField.hidden = bgMode !== "manual";

  if (mode === "chunks" && sourceWidth !== null && sourceWidth <= sourceHeight) {
    setStatus("Carousel chunks require a landscape image.", true);
  } else if (statusText.textContent === "Carousel chunks require a landscape image.") {
    setStatus("");
  }
}

function clearResults() {
  downloadAll.hidden = true;
  resultGrid.className = "result-grid empty";
  resultGrid.innerHTML = `
    <div class="empty-state">
      <span class="empty-mark"></span>
      <span>Your processed images will appear here.</span>
    </div>
  `;
}

function renderResults(data) {
  resultGrid.className = "result-grid";
  resultGrid.innerHTML = "";
  expiry.textContent = `Generated files expire in ${data.expiresInMinutes} minutes. Background: ${data.background}.`;
  downloadAll.hidden = false;
  downloadAll.href = data.zip.url;
  downloadAll.download = data.zip.name;

  for (const file of data.files) {
    const card = document.createElement("article");
    card.className = "result-card";
    card.innerHTML = `
      <img src="${file.url}" alt="${file.name}">
      <div class="result-body">
        <div class="result-name">${file.name}</div>
        <div class="result-size">${file.width} x ${file.height}px</div>
        <a class="button" href="${file.url}" download="${file.name}">Download</a>
      </div>
    `;
    resultGrid.appendChild(card);
  }
}

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  clearResults();
  if (!file) {
    fileLabel.textContent = "Choose an image";
    sourceMeta.textContent = "No image selected";
    sourceWidth = null;
    sourceHeight = null;
    preview.hidden = true;
    preview.removeAttribute("src");
    return;
  }

  fileLabel.textContent = file.name;
  const url = URL.createObjectURL(file);
  preview.onload = () => {
    sourceWidth = preview.naturalWidth;
    sourceHeight = preview.naturalHeight;
    sourceMeta.textContent = `${sourceWidth} x ${sourceHeight}px`;
    syncOptions();
    URL.revokeObjectURL(url);
  };
  preview.src = url;
  preview.hidden = false;
});

for (const control of document.querySelectorAll("input, select")) {
  control.addEventListener("change", syncOptions);
}
syncOptions();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files[0];
  if (!file) {
    setStatus("Choose an image first.", true);
    return;
  }
  if (selectedValue("mode") === "chunks" && sourceWidth !== null && sourceWidth <= sourceHeight) {
    setStatus("Carousel chunks require a landscape image.", true);
    return;
  }

  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  setStatus("Processing...");

  const payload = new FormData();
  payload.append("image", file);
  payload.append("mode", selectedValue("mode"));
  payload.append(
    "aspect_ratio",
    ratioSelect.value === "custom" ? customRatio.value.trim() : ratioSelect.value,
  );
  payload.append("background_mode", selectedValue("background_mode"));
  payload.append("background_color", backgroundColor.value);
  payload.append("chunk_count", chunkCount.value);
  payload.append("carousel_padding", carouselPadding.value);
  payload.append("output_format", outputFormat.value);

  try {
    const response = await fetch("/api/process", {
      method: "POST",
      body: payload,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Processing failed.");
    }
    renderResults(data);
    setStatus(`Created ${data.files.length} file${data.files.length === 1 ? "" : "s"}.`);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    button.disabled = false;
  }
});

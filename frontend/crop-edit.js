let stages = ["question_paper", "marking_scheme", "solution_script", "answer_script"]

// Helper function to concatenate images vertically
function concatenateImages(images) {
  let maxWidth = 0, totalHeight = 0;
  images.forEach(img => {
    maxWidth = Math.max(maxWidth, img.naturalWidth);
    totalHeight += img.naturalHeight;
  });
  const canvas = document.createElement('canvas');
  canvas.width = maxWidth;
  canvas.height = totalHeight;
  const ctx = canvas.getContext('2d');
  let currentY = 0;
  images.forEach(img => {
    const x = (maxWidth - img.naturalWidth) / 2;
    ctx.drawImage(img, x, currentY);
    currentY += img.naturalHeight;
  });
  return canvas.toDataURL();
}

// Global variables for selection and responses
pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/2.16.105/pdf.worker.min.js';
let isSelecting = false, startX = 0, startY = 0;
let currentOverlay = null, currentSelectionBox = null, pathPoints = [];
let cutMode = 'box';
let currentQuestionIndex = 0;
let currentPartIndex = -1;
let tempResponse = null;
let questionResponses = [];
let questions = [];
let regionSelections = [];
let regionCounter = 1;
let currentBoxRect = null;

let document_type = null;


let selectMode = 'sequential';  // 'sequential' or 'dropdown'


// ─── NEW: toggle UI when mode changes ──────────────────────────
function updateModeUI() {
  const dropdownLabel = document.getElementById('selector-label');
  const partBtn       = document.getElementById('part-btn');
  const submitBtn     = document.getElementById('submit-btn');

  if (selectMode === 'dropdown') {
    dropdownLabel.style.display = 'flex';
    partBtn.style.display       = 'inline-flex';   // ← now visible in dropdown
    submitBtn.style.display     = 'inline-flex';
  } else {
    dropdownLabel.style.display = 'none';
    partBtn.style.display       = 'inline-flex';
    submitBtn.style.display     = 'none';
  }
}




// ─── NEW: populate question dropdown ───────────────────────────
function populateQuestionSelector() {
  const selector = document.getElementById('question-selector');
  selector.innerHTML = '';
  questions.forEach((q, idx) => {
    const opt = document.createElement('option');
    opt.value = idx;
    opt.text  = `Question ${q.question_number}`;
    selector.appendChild(opt);
  });
  selector.addEventListener('change', e => {
    // switch current question
    const idx = parseInt(e.target.value, 10);
    tempResponse = createTempResponse(idx);
    setCurrentQuestion(idx, -1);
    clearCroppedImages();
    clearRegionMarkers();
  });
}

async function initialise_crop_edit(examId){
  document.getElementById('part-btn').addEventListener('click', async () => {
    await saveCurrentSelections();
  
    if (selectMode === 'dropdown') {
      // just save/overwrite & re-render, stay on same Q
      const idx = questionResponses.findIndex(r => r.question_id === tempResponse.question_id);
      if (idx >= 0) questionResponses[idx] = JSON.parse(JSON.stringify(tempResponse));
      else          questionResponses.push(JSON.parse(JSON.stringify(tempResponse)));
  
      renderAllResponses();
      clearCroppedImages();
      clearRegionMarkers();
  
      // reset tempResponse for this same question
      tempResponse = createTempResponse(currentQuestionIndex);
      setCurrentQuestion(currentQuestionIndex, -1);
      document.getElementById('question-selector').value = currentQuestionIndex;
    } else {
      // Sequential: push & move to next question
      questionResponses.push(tempResponse);
      renderAllResponses();
      clearCroppedImages();
      clearRegionMarkers();
  
      currentQuestionIndex++;
      if (currentQuestionIndex < questions.length) {
        tempResponse = createTempResponse(currentQuestionIndex);
        setCurrentQuestion(currentQuestionIndex, -1);
      } else {
        document.getElementById('submit-btn').style.display   = 'block';
      }
    }
  });
  
      
    await load_pdf_in_cropper(examId);
    
    const modal = document.getElementById("edit-modal");
    const modalContent = document.getElementById("edit-order-container");
    const closeModalSpan = document.querySelector(".modal .close");
    
    closeModalSpan.onclick = () => modal.style.display = "none";
    window.onclick = event => { if (event.target == modal) modal.style.display = "none"; };
    document.getElementById('edit-order-btn').addEventListener('click', openEditOrderModal);
    document.getElementById('save-edit-order').addEventListener('click', saveEditOrder);
    document.getElementById('submit-btn').addEventListener('click', () => {
        handleSubmit(examId);
    });

    document.querySelectorAll('input[name="cut-mode"]').forEach(radio => {
      radio.addEventListener('change', e => cutMode = e.target.value);
    });

    // MANUAL SELECT: radio buttons
    // document.querySelectorAll('input[name="select-mode"]').forEach(radio => {
    //   radio.addEventListener('change', e => {
    //     selectMode = e.target.value;
    //     updateModeUI();
    //   });
    // });
  
  }

function openEditOrderModal() {
    const modal = document.getElementById("edit-modal");
    const modalContent = document.getElementById("edit-order-container");
    modal.style.display = "block";
    modalContent.innerHTML = "";
    const thumbnails = document.getElementById('cropped-images').querySelectorAll('div');
    thumbnails.forEach(wrapper => modalContent.appendChild(wrapper.cloneNode(true)));
    new Sortable(modalContent, { animation: 150 });
}

function saveEditOrder(){
    const sidebar = document.getElementById('cropped-images');
    sidebar.innerHTML = "";
    const newOrder = modalContent.querySelectorAll('div');
    newOrder.forEach(wrapper => sidebar.appendChild(wrapper));
    updateRegionNumbers();
    modal.style.display = "none";
}

async function load_pdf_in_cropper(examId) {
  // Load questions and parts
  fetch(`/exams/${examId}/questions/parts`)
    .then(res => res.json())
    .then(data => {
      questions = data.map(q => ({
        ...q,
        parts: JSON.parse(q.part_labels) || []
      }));
      if (questions.length > 0) {
        populateQuestionSelector();

        tempResponse = createTempResponse(0);
        setCurrentQuestion(0, -1);
      }
    })
    .catch(err => console.error('Error fetching questions:', err));
  
  // Load PDF answer script
  fetch("/get-info", { headers: { "Content-Type": "application/json" } })          // REMOVE THIS LATER AND SWITCH TO MORE EFFICIENT (JWT Maybe)
    .then(response => response.json())
    .then(user_data => {
        doc_stage = getDocStage(currentStage);
        document_type = stages[doc_stage];
        console.log(doc_stage, document_type);
        if(user_data.user.is_professor){
          selectMode = 'dropdown';  // professors can only use dropdown mode
          updateModeUI();
        }else{
          selectMode = 'sequential'; // students can only use sequential mode
          updateModeUI();
        }
        if(document_type != "answer_script" && !(user_data.user.is_professor)){
            alert("You are not allowed to view this document type.");
            return;
        }
        fetch(`/student/exam/${examId}/document/${document_type}`)
          .then(res => {
              if (!res.ok) throw new Error(`${document_type} not found.`);
              return res.json();
            })
            .then(data => {
              if (data.file_path) {
                data.file_path = "../" + data.file_path.replace("./", "");
                fetch(data.file_path)
                  .then(response => response.arrayBuffer())
                  .then(arrayBuffer => loadPDF(arrayBuffer))
                  .catch(err => { console.error("Error fetching PDF:", err); alert("Failed to load PDF."); });
              } else {
                alert(`No file path found for ${document_type} file.`);
              }
            })
            .catch(err => { console.error("Error loading script metadata:", err); alert(`Unable to load ${document_type}.`); });
      
          renderAllResponses();
    });
}

function createTempResponse(questionIndex) {
  const question = questions[questionIndex];
  return {
    question_id: question.id,
    question_number: question.question_number,
    text_images: [],
    table_images: [],
    diagram_images: [],
    parts: question.parts.map(part_label => ({
      part_label: part_label,
      text_images: [],
      table_images: [],
      diagram_images: []
    }))
  };
}

function setCurrentQuestion(questionIndex, partIndex) {
  currentQuestionIndex = questionIndex;
  currentPartIndex = partIndex;
  const question = questions[questionIndex];
  console.log(question);
  let label = partIndex === -1 ? 
    `Question ${question.question_number}` : 
    `Part ${question.parts[partIndex]} of Question ${question.question_number}`;
  document.getElementById('question-number').textContent = label;

  // Update the combined button text based on the parts status.
  const btn = document.getElementById('part-btn');
  // if (question.parts.length > 0) {
  //   if (currentPartIndex === -1 || currentPartIndex < question.parts.length - 1) {
  //     btn.textContent = "Next Part";
  //   } else {
  //     btn.textContent = "Done";
  //   }
  // } else {
  btn.textContent = "Done";
  // }
}

function loadPDF(arrayBuffer) {
  const pdfContainer = document.getElementById('pdf-container');
  pdfContainer.innerHTML = '';
  pdfjsLib.getDocument(arrayBuffer).promise.then(pdf => {
    for (let i = 1; i <= pdf.numPages; i++) {
      pdf.getPage(i).then(renderPage);
    }
  }).catch(err => alert('Failed to load PDF.'));
}

function renderPage(page) {
  const displayScale = 1, renderScale = 2;
  const displayViewport = page.getViewport({ scale: displayScale });
  const renderViewport = page.getViewport({ scale: renderScale });
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  canvas.width = renderViewport.width;
  canvas.height = renderViewport.height;
  canvas.style.width = `${displayViewport.width}px`;
  canvas.style.height = `${displayViewport.height}px`;
  const pageContainer = document.createElement('div');
  pageContainer.className = 'page-container';
  pageContainer.style.width = `${displayViewport.width}px`;
  pageContainer.style.height = `${displayViewport.height}px`;
  const overlay = document.createElement('div');
  overlay.className = 'overlay';
  overlay.style.width = `${displayViewport.width}px`;
  overlay.style.height = `${displayViewport.height}px`;
  overlay.dataset.ratio = renderScale;
  const selectionBox = document.createElement('div');
  selectionBox.className = 'selection-box';
  overlay.appendChild(selectionBox);
  const freehandCanvas = document.createElement('canvas');
  freehandCanvas.className = 'freehand-canvas';
  freehandCanvas.width = displayViewport.width;
  freehandCanvas.height = displayViewport.height;
  freehandCanvas.style.width = `${displayViewport.width}px`;
  freehandCanvas.style.height = `${displayViewport.height}px`;
  freehandCanvas.style.display = 'none';
  overlay.appendChild(freehandCanvas);
  pageContainer.appendChild(canvas);
  pageContainer.appendChild(overlay);
  document.getElementById('pdf-container').appendChild(pageContainer);
  page.render({ canvasContext: context, viewport: renderViewport }).promise.then(() => {
    overlay.addEventListener('mousedown', startSelection);
    overlay.addEventListener('mousemove', updateSelection);
    overlay.addEventListener('mouseup', endSelection);
  });
}

function startSelection(event) {
  isSelecting = true;
  regionSelections.forEach(region => {
    if(region.partSelect) region.partSelect.style.pointerEvents = 'none';
    region.selectEl.style.pointerEvents = 'none';
    region.deleteButton.style.pointerEvents = 'none';
  });
  currentOverlay = event.currentTarget;
  if (cutMode === 'box') {
    currentSelectionBox = currentOverlay.querySelector('.selection-box');
    const rect = event.currentTarget.getBoundingClientRect();
    startX = event.clientX - rect.left;
    startY = event.clientY - rect.top;
    currentSelectionBox.style.left = startX + 'px';
    currentSelectionBox.style.top = startY + 'px';
    currentSelectionBox.style.width = '0px';
    currentSelectionBox.style.height = '0px';
    currentSelectionBox.style.display = 'block';
  } else if (cutMode === 'freehand') {
    const freehandCanvas = currentOverlay.querySelector('.freehand-canvas');
    freehandCanvas.style.display = 'block';
    const ctx = freehandCanvas.getContext('2d');
    ctx.clearRect(0, 0, freehandCanvas.width, freehandCanvas.height);
    ctx.beginPath();
    ctx.moveTo(event.offsetX, event.offsetY);
    ctx.strokeStyle = 'blue';
    ctx.lineWidth = 2;
    pathPoints = [{ x: event.offsetX, y: event.offsetY }];
  }
}

function updateSelection(event) {
  if (!isSelecting) return;
  if (cutMode === 'box') {
    const rect = event.currentTarget.getBoundingClientRect();
    const currentX = event.clientX - rect.left;
    const currentY = event.clientY - rect.top;
    const minX = Math.min(startX, currentX), minY = Math.min(startY, currentY);
    const width = Math.abs(currentX - startX), height = Math.abs(currentY - startY);
    currentSelectionBox.style.left = minX + 'px';
    currentSelectionBox.style.top = minY + 'px';
    currentSelectionBox.style.width = width + 'px';
    currentSelectionBox.style.height = height + 'px';
    currentBoxRect = { minX, minY, width, height };
  } else if (cutMode === 'freehand') {
    const freehandCanvas = currentOverlay.querySelector('.freehand-canvas');
    const ctx = freehandCanvas.getContext('2d');
    ctx.lineTo(event.offsetX, event.offsetY);
    ctx.stroke();
    pathPoints.push({ x: event.offsetX, y: event.offsetY });
  }
}

function endSelection() {
  if (!isSelecting) return;
  isSelecting = false;
  regionSelections.forEach(region => {
    if(region.partSelect) region.partSelect.style.pointerEvents = 'auto';
    region.selectEl.style.pointerEvents = 'auto';
    region.deleteButton.style.pointerEvents = 'auto';
  });
  const ratio = parseFloat(currentOverlay.dataset.ratio);
  if (cutMode === 'box') {
    currentSelectionBox.style.display = 'none';
    if (!currentBoxRect || currentBoxRect.width < 5 || currentBoxRect.height < 5) return;
    const regionRect = { left: currentBoxRect.minX, top: currentBoxRect.minY, width: currentBoxRect.width, height: currentBoxRect.height };
    const canvasMinX = currentBoxRect.minX * ratio, canvasMinY = currentBoxRect.minY * ratio;
    const canvasWidth = currentBoxRect.width * ratio, canvasHeight = currentBoxRect.height * ratio;
    cropAndAddImage(canvasMinX, canvasMinY, canvasWidth, canvasHeight, regionRect, 'box', null);
    currentBoxRect = null;
  } else if (cutMode === 'freehand') {
    const freehandCanvas = currentOverlay.querySelector('.freehand-canvas');
    freehandCanvas.style.display = 'none';
    const bbox = getBoundingBox(pathPoints);
    if (!bbox || bbox.width < 5 || bbox.height < 5) return;
    const regionRect = { left: bbox.minX, top: bbox.minY, width: bbox.width, height: bbox.height };
    cropWithPath(pathPoints, ratio, regionRect);
    pathPoints = [];
  }
}

function getBoundingBox(points) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  points.forEach(p => {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  });
  return { minX, minY, width: maxX - minX, height: maxY - minY };
}

function cropAndAddImage(canvasMinX, canvasMinY, canvasWidth, canvasHeight, regionRect, type, freehandData) {
  const canvas = currentOverlay.previousElementSibling;
  const newCanvas = document.createElement('canvas');
  newCanvas.width = canvasWidth;
  newCanvas.height = canvasHeight;
  const ctx = newCanvas.getContext('2d');
  ctx.drawImage(canvas, canvasMinX, canvasMinY, canvasWidth, canvasHeight, 0, 0, canvasWidth, canvasHeight);
  const dataURL = newCanvas.toDataURL();
  addRegionSelection(regionRect, dataURL, currentOverlay, type, freehandData);
}

function cropWithPath(points, ratio, regionRect) {
  const bbox = getBoundingBox(points);
  const canvasMinX = bbox.minX * ratio, canvasMinY = bbox.minY * ratio;
  const canvasWidth = bbox.width * ratio, canvasHeight = bbox.height * ratio;
  const newCanvas = document.createElement('canvas');
  newCanvas.width = canvasWidth;
  newCanvas.height = canvasHeight;
  const ctx = newCanvas.getContext('2d');
  ctx.save();
  ctx.translate(-canvasMinX, -canvasMinY);
  ctx.beginPath();
  points.forEach((p, i) => {
    const canvasX = p.x * ratio, canvasY = p.y * ratio;
    if (i === 0) ctx.moveTo(canvasX, canvasY);
    else ctx.lineTo(canvasX, canvasY);
  });
  ctx.closePath();
  ctx.clip();
  const canvas = currentOverlay.previousElementSibling;
  ctx.drawImage(canvas, 0, 0);
  ctx.restore();
  const dataURL = newCanvas.toDataURL();
  addRegionSelection(regionRect, dataURL, currentOverlay, 'freehand', points);
}

function addRegionSelection(regionRect, dataURL, overlay, type, freehandData) {
  const regionId = regionCounter++;
  const marker = document.createElement('div');
  marker.className = 'region-marker';
  if (type === 'freehand') marker.classList.add('freehand');
  marker.style.left   = regionRect.left + 'px';
  marker.style.top    = regionRect.top  + 'px';
  marker.style.width  = regionRect.width + 'px';
  marker.style.height = regionRect.height+ 'px';

  // build the label container
  const labelContainer = document.createElement('div');
  labelContainer.className = 'region-label';

  // 1) region number, 2) type dropdown, 3) part dropdown (if any), 4) delete button
  let html = `
    <span class="region-number">0</span>
    <select class="region-type" id="region-type-selector">
      <option value="Text">Text</option>
      <option value="Table">Table</option>
      <option value="Diagram">Diagram</option>
    </select>
  `;
  // PART dropdown: only if this question has parts
  const parts = questions[currentQuestionIndex].parts;
  if (parts && parts.length > 0) {
    html += `<select class="region-type" id="region-part-selector">
                <option value="">Main</option>
              </select>`;
  }

  html += `<span class="delete-region" data-region-id="${regionId}">×</span>`;
  labelContainer.innerHTML = html;
  marker.appendChild(labelContainer);

  // wire up the selects + delete
  const selectEl   = labelContainer.querySelector('#region-type-selector');
  const partSelect = labelContainer.querySelector('#region-part-selector');
  const deleteBtn  = labelContainer.querySelector('.delete-region');

  // populate the part-selector
  if (partSelect) {
    console.log(partSelect);
    parts.forEach(p => {
      const opt = document.createElement('option');
      opt.value       = p;
      opt.textContent = `Part ${p}`;
      partSelect.appendChild(opt);
    });
    // prevent clicks on it from starting a crop
    ['click','mousedown'].forEach(evt =>
      partSelect.addEventListener(evt, e => e.stopPropagation())
    );

    partSelect.style.pointerEvents = 'auto';
  }
  // selectEl.addEventListener('mousedown', e => e.stopPropagation());
  deleteBtn.addEventListener('mousedown', e => e.stopPropagation());
  deleteBtn.addEventListener('click', e => {
    e.stopPropagation();
    deleteRegion(e.target.dataset.regionId);
  });

  if (type === 'freehand' && freehandData) {
    const svgNS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("width", regionRect.width);
    svg.setAttribute("height", regionRect.height);
    const pointsAttr = freehandData.map(p => (p.x - regionRect.left) + "," + (p.y - regionRect.top)).join(" ");
    const polyline = document.createElementNS(svgNS, "polyline");
    polyline.setAttribute("points", pointsAttr);
    polyline.setAttribute("stroke", "red");
    polyline.setAttribute("stroke-width", "2");
    polyline.setAttribute("fill", "none");
    svg.appendChild(polyline);
    marker.appendChild(svg);
  }

  marker.style.pointerEvents = 'none';
  selectEl.style.pointerEvents = 'auto';
  deleteBtn.style.pointerEvents = 'auto';

  overlay.appendChild(marker);
  regionSelections.push({
    regionId,
    markerElement: marker,
    overlay,
    selectEl,
    partSelect,   // <— remember it here
    deleteButton: deleteBtn
  });

  addImageToSidebar(dataURL, regionId);
  updateRegionNumbers();
}


function addImageToSidebar(dataURL, regionId) {
  const img = document.createElement('img');
  img.src = dataURL;
  const wrapper = document.createElement('div');
  wrapper.dataset.regionId = regionId;
  wrapper.className = 'response-image-wrapper';
  wrapper.appendChild(img);
  const delSpan = document.createElement('span');
  delSpan.className = 'delete-response-image';
  delSpan.textContent = '×';
  delSpan.addEventListener('click', () => {
    wrapper.parentNode.removeChild(wrapper);
    deleteRegion(regionId);
  });
  wrapper.appendChild(delSpan);
  document.getElementById('cropped-images').appendChild(wrapper);
}

function updateRegionNumbers() {
  const imageWrappers = document.getElementById('cropped-images').querySelectorAll('div');
  imageWrappers.forEach((wrapper, index) => {
    const regionId = wrapper.dataset.regionId;
    const region = regionSelections.find(r => r.regionId == Number(regionId));
    if (region) {
      const numberSpan = region.markerElement.querySelector('.region-number');
      if (numberSpan) numberSpan.textContent = index + 1;
      region.markerElement.style.zIndex = index + 1;
    }
  });
}

function deleteRegion(regionId) {
  const id = Number(regionId);
  const regionIndex = regionSelections.findIndex(r => r.regionId === id);
  if (regionIndex === -1) return;
  const region = regionSelections[regionIndex];
  if (region.markerElement && region.overlay.contains(region.markerElement))
    region.overlay.removeChild(region.markerElement);
  const sidebar = document.getElementById('cropped-images');
  const wrapper = sidebar.querySelector(`div[data-region-id="${id}"]`);
  if (wrapper) sidebar.removeChild(wrapper);
  regionSelections.splice(regionIndex, 1);
  updateRegionNumbers();
}

function clearCroppedImages() {
  document.getElementById('cropped-images').innerHTML = '';
}

function clearRegionMarkers() {
  regionSelections.forEach(item => {
    if (item.markerElement && item.overlay.contains(item.markerElement))
      item.overlay.removeChild(item.markerElement);
  });
  regionSelections = [];
  regionCounter = 1;
}
 

function waitForImageLoad(img) {
  return new Promise(res => {
    img.onload  = () => res();
    img.onerror = () => res();
  });
}

// Updated asynchronous function to save current selections
async function saveCurrentSelections() {
  // 1. Gather all cropped thumbnails
  const wrappers = document.getElementById('cropped-images')
                      .querySelectorAll('div.response-image-wrapper');
  
  // 2. Build “main” and per-part buckets
  const mainBucket = { Text: [], Table: [], Diagram: [] };
  const partsList  = questions[currentQuestionIndex].parts || [];
  const partsMap   = {};
  partsList.forEach(p => {
    partsMap[p] = { Text: [], Table: [], Diagram: [] };
  });

  // 3. Assign each crop to its bucket based on its region’s selects
  wrappers.forEach(wrapper => {
    const rid = Number(wrapper.dataset.regionId);
    const region = regionSelections.find(r => r.regionId === rid);
    const kind   = region.selectEl.value;            // "Text" / "Table" / "Diagram"
    const part   = region.partSelect?.value || "";   // "" ⇒ main; else partLabel
    const src    = wrapper.querySelector('img').src;

    if (part) partsMap[part][kind].push(src);
    else      mainBucket[kind].push(src);
  });

  // 5. Helper: prepend a label to an image
  async function processImageWithLabel(src, labelText) {
    // create label image
    const labelData = createTextImage(labelText);
    const labelImg  = new Image();
    labelImg.src    = labelData;
    await waitForImageLoad(labelImg);

    // load base image
    const baseImg = new Image();
    baseImg.src   = src;
    await waitForImageLoad(baseImg);

    // concatenate label atop
    return concatenateImages([labelImg, baseImg]);
  }

  // 6. Process MAIN question images
  const qNumText = `Question Number ${questions[currentQuestionIndex].question_number}`;
  let mainText     = [];
  let mainTable    = [];
  let mainDiagram  = [];

  // — Text stack (label + all text regions)
  if (mainBucket.Text.length > 0) {
    // load label
    const labelImg = new Image();
    labelImg.src   = createTextImage(qNumText);
    await waitForImageLoad(labelImg);

    // load each text region
    const textImgs = await Promise.all(
      mainBucket.Text.map(src => {
        const img = new Image();
        img.src   = src;
        return waitForImageLoad(img).then(() => img);
      })
    );

    mainText = [ concatenateImages([labelImg, ...textImgs]) ];
  }

  // — Tables & Diagrams (each gets its own labeled image)
  mainTable   = await Promise.all(mainBucket.Table.map(src => processImageWithLabel(src, qNumText)));
  mainDiagram = await Promise.all(mainBucket.Diagram.map(src => processImageWithLabel(src, qNumText)));

  tempResponse.text_images    = mainText;
  tempResponse.table_images   = mainTable;
  tempResponse.diagram_images = mainDiagram;

  // 7. Process each PART
  await Promise.all(partsList.map(async (partLabel, idx) => {
    const bucket = partsMap[partLabel];
    const partObj = tempResponse.parts[idx];
    const pText   = `Part ${partLabel}`;

    // — Text for this part
    if (bucket.Text.length > 0) {
      const labelImg = new Image();
      labelImg.src   = createTextImage(pText);
      await waitForImageLoad(labelImg);

      const textImgs = await Promise.all(
        bucket.Text.map(src => {
          const img = new Image();
          img.src   = src;
          return waitForImageLoad(img).then(() => img);
        })
      );

      partObj.text_images = [ concatenateImages([labelImg, ...textImgs]) ];
    } else {
      partObj.text_images = [];
    }

    // — Table & Diagram for this part
    partObj.table_images   = await Promise.all(bucket.Table.map(src => processImageWithLabel(src, pText)));
    partObj.diagram_images = await Promise.all(bucket.Diagram.map(src => processImageWithLabel(src, pText)));
  }));
}



function createResponseDiv(response) {
  const qDiv = document.createElement('div');
  qDiv.className = "question-response";
  const header = document.createElement('h3');
  header.textContent = "Question " + response.question_number;
  const redoBtn = document.createElement('button');
  redoBtn.textContent = "Redo";
  redoBtn.addEventListener('click', () => {
    if (confirm(`Redoing will erase your current selections for Question ${response.question_number}. Proceed?`)) {
      questionResponses = questionResponses.filter(r => r.question_id !== response.question_id);
      renderAllResponses();
      clearCroppedImages();
      clearRegionMarkers();
      currentQuestionIndex = questions.findIndex(q => q.id === response.question_id);
      tempResponse = createTempResponse(currentQuestionIndex);
      setCurrentQuestion(currentQuestionIndex, -1);
  
      // ─── NEW: sync dropdown on redo ─────────────────────────────
      const sel = document.getElementById('question-selector');
      if (sel) sel.value = currentQuestionIndex;
    }
  });
  
  header.appendChild(redoBtn);
  qDiv.appendChild(header);
  appendImageGroup(qDiv, 'Text Images', response.text_images);
  appendImageGroup(qDiv, 'Table Images', response.table_images);
  appendImageGroup(qDiv, 'Diagram Images', response.diagram_images);
  response.parts.forEach(part => {
    const partHeader = document.createElement('h4');
    partHeader.textContent = `Part ${part.part_label}`;
    qDiv.appendChild(partHeader);
    appendImageGroup(qDiv, 'Text Images', part.text_images);
    appendImageGroup(qDiv, 'Table Images', part.table_images);
    appendImageGroup(qDiv, 'Diagram Images', part.diagram_images);
  });
  return qDiv;
}

function appendImageGroup(parent, label, images) {
  const group = document.createElement('div');
  group.className = 'response-group';
  const strong = document.createElement('strong');
  strong.textContent = `${label}: `;
  group.appendChild(strong);
  
  if (images.length > 0) {
    images.forEach(src => {
      const img = document.createElement('img');
      img.src = src;
      group.appendChild(img);
    });
  } else {
    group.appendChild(document.createTextNode('None'));
  }
  parent.appendChild(group);
}

// Create text image from label
function createTextImage(text, font = "bold 24px Poppins", textColor = "#000", bgColor = "#fff") {
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  ctx.font = font;
  const metrics = ctx.measureText(text);
  canvas.width = metrics.width + 20;
  canvas.height = 40;
  ctx.font = font;
  ctx.fillStyle = bgColor;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = textColor;
  ctx.fillText(text, 10, 28);
  return canvas.toDataURL();
}

function renderAllResponses() {
  const container = document.getElementById('responses-container');
  // always start with the heading
  if(document_type == "answer_script"){
    container.innerHTML = '<h2>Question Responses</h2>';
  }else if(document_type == "marking_scheme"){
    container.innerHTML = '<h2>Marking Scheme</h2>';
  }else if(document_type == "question_paper"){
    container.innerHTML = '<h2>Question Paper</h2>';
  }else if(document_type == "solution_script"){
    container.innerHTML = '<h2>Solution Script</h2>';
  }
  
  if (questionResponses.length === 0) {
    // show the italic prompt
    const p = document.createElement('p');
    p.className = 'empty-message';
    p.textContent = 'No regions selected yet. Start by selecting your first!';
    container.appendChild(p);
  } else {
    // normal rendering
    questionResponses
      .sort((a, b) => a.question_number - b.question_number)
      .forEach(resp => container.appendChild(createResponseDiv(resp)));
  }
}

function loadImageFromDataUrl(dataUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.src = dataUrl;
    img.onload = () => resolve(img);
    img.onerror = reject;
  });
}

async function handleSubmit(examId){
  // Process each question response before sending.
  const processedResponses = await Promise.all(
    questionResponses.map(async (response, idx) => {
      // Gather question-level and part-level text images
      const topLevel = response.text_images || [];
      const partsLevel = (response.parts || [])
        .flatMap(part => part.text_images || []);

      let finalTextImages = [];

      // If any text images exist at either level, process them
      if (topLevel.length > 0 || partsLevel.length > 0) {
        let mergedImage;

        if (topLevel.length > 0) {
          // Standard: stitch question images + part images
          const allTextDataURIs = [...topLevel, ...partsLevel].filter(Boolean);
          const images = await Promise.all(
            allTextDataURIs.map(src => loadImageFromDataUrl(src))
          );
          mergedImage = concatenateImages(images);
        } else {
          // No question-level images but parts exist: stitch parts then prepend label
          // 1) Stitch all part images
          const partImgs = await Promise.all(
            partsLevel.map(src => loadImageFromDataUrl(src))
          );
          const mergedPartsDataUrl = concatenateImages(partImgs);
          const mergedPartsImg = await loadImageFromDataUrl(mergedPartsDataUrl);
          // 2) Create label image for question number
          const labelText = `Question Number ${response.question_number}`;
          const labelImg = new Image();
          labelImg.src = createTextImage(labelText);
          await waitForImageLoad(labelImg);
          // 3) Prepend label atop merged parts
          mergedImage = concatenateImages([labelImg, mergedPartsImg]);
        }

        finalTextImages = [mergedImage];
      }

      // Tables & diagrams: include both top-level and part-level
      let finalTableImages = response.table_images ? [...response.table_images] : [];
      let finalDiagramImages = response.diagram_images ? [...response.diagram_images] : [];
      if (response.parts) {
        for (const part of response.parts) {
          if (part.table_images)   finalTableImages.push(...part.table_images);
          if (part.diagram_images) finalDiagramImages.push(...part.diagram_images);
        }
      }

      return {
        question_id: response.question_id,
        question_number: response.question_number,
        original_index: idx,
        text_images: finalTextImages,
        table_images: finalTableImages,
        diagram_images: finalDiagramImages
      };
    })
  );

  // 2. Submit each processed response
  const submitPromises = processedResponses.map(resp => 
    fetch(`/exam/${examId}/question_response/${document_type}`, {
      method: 'POST',
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(resp)
    }).then(r => r.json())
      .then(data => console.log("Individual Question Images Saved :", data))
  );
  await Promise.all(submitPromises);

  // 3. Only run the “process-text-images” endpoint in Sequential mode
  if (document_type == 'answer_script') {
    try{
      const procRes = await fetch(
        `/api/${examId}/process-text-images/${document_type}`, {
          method: 'POST',
          headers: { "Content-Type": "application/json" }
        }
      );
      await procRes.json();
      alert("Responses submitted and processed successfully!");

      await postExamStage(7); // Update the exam stage to 7 (Grading Started)
    } catch(err) {
      console.error("Processing/Extraction error:", err);
      alert("Processing/Extraction of text from individual question images failed.");
    }
  } else {
    // Dropdown mode: skip processing step
    alert("Responses submitted successfully!");
  }
}
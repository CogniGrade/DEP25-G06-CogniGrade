// Object to store cropped regions per question
const questionRegions = {};
let currentQuestionId = null;

function getQueryParam(param) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(param);
  }

// Fetch questions from the API
async function fetchQuestions() {
    const examId = getQueryParam("exam_id");
    try {
        const response = await fetch(`/exams/${examId}/questions/all`);
        const questions = await response.json();
        displayQuestions(questions);
    } catch (error) {
        console.error('Error fetching questions:', error);
    }
}

// Display questions in the UI
function displayQuestions(questions) {
    const questionsList = document.getElementById('questions-list');
    questionsList.innerHTML = '';
    questions.forEach(q => {
        const li = document.createElement('li');
        li.textContent = `Question ${q.question_number}: ${q.text}`;
        const associateBtn = document.createElement('button');
        associateBtn.textContent = 'Associate Regions';
        associateBtn.addEventListener('click', () => {
            currentQuestionId = q.id;
            alert(`Now selecting regions for Question ${q.question_number}`);
        });
        li.appendChild(associateBtn);
        questionsList.appendChild(li);
    });
}

// Assume this function is called when a region is cropped (e.g., from your existing PDF editor logic)
function onRegionCropped(dataURL) {
    if (!currentQuestionId) {
        alert('Please select a question to associate this region with.');
        return;
    }

    // Create a dropdown for association options
    const imgContainer = document.createElement('div');
    const img = document.createElement('img');
    img.src = dataURL;
    img.style.maxWidth = '100px';

    const select = document.createElement('select');
    const options = ['Answer', 'Working', 'Notes'];
    options.forEach(opt => {
        const option = document.createElement('option');
        option.value = opt.toLowerCase();
        option.textContent = opt;
        select.appendChild(option);
    });

    imgContainer.appendChild(img);
    imgContainer.appendChild(select);
    document.getElementById('cropped-images').appendChild(imgContainer);

    // Store the region with its association
    if (!questionRegions[currentQuestionId]) {
        questionRegions[currentQuestionId] = [];
    }
    questionRegions[currentQuestionId].push({ dataURL, association: select.value });

    // Update association when changed
    select.addEventListener('change', () => {
        const region = questionRegions[currentQuestionId].find(r => r.dataURL === dataURL);
        region.association = select.value;
    });
}

// Concatenate images when "Done" is pressed
document.getElementById('done-btn').addEventListener('click', () => {
    if (!currentQuestionId || !questionRegions[currentQuestionId]) {
        alert('No regions selected for the current question.');
        return;
    }

    const regions = questionRegions[currentQuestionId];
    const concatenatedImage = concatenateImages(regions.map(r => r.dataURL));
    console.log(`Concatenated image for Question ${currentQuestionId}:`, concatenatedImage);
    // Optionally display or store the concatenated image
    currentQuestionId = null; // Reset after done
});

// Concatenate images vertically
function concatenateImages(imageURLs) {
    let maxWidth = 0;
    let totalHeight = 0;
    const images = imageURLs.map(url => {
        const img = new Image();
        img.src = url;
        maxWidth = Math.max(maxWidth, img.width || 0);
        totalHeight += img.height || 0;
        return img;
    });

    const canvas = document.createElement('canvas');
    canvas.width = maxWidth;
    canvas.height = totalHeight;
    const ctx = canvas.getContext('2d');
    let currentY = 0;

    images.forEach(img => {
        ctx.drawImage(img, 0, currentY);
        currentY += img.height;
    });

    return canvas.toDataURL();
}

// Dummy endpoint simulation
document.getElementById('send-btn').addEventListener('click', () => {
    Object.entries(questionRegions).forEach(([questionId, regions]) => {
        console.log(`Question ${questionId} Regions:`, regions);
        // Placeholder for future POST request
        // fetch('/dummy-endpoint', {
        //     method: 'POST',
        //     headers: { 'Content-Type': 'application/json' },
        //     body: JSON.stringify({ questionId, regions })
        // });
    });
    alert('Question images logged to console. Implement backend logic later.');
});

// Initialize with an example examId (replace with your logic to get examId)
fetchQuestions(1); // Example examId
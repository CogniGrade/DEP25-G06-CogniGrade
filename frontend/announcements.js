// ===== ANNOUNCEMENTS FEATURE =====
let announcements = JSON.parse(localStorage.getItem("announcements")) || [];

// Expand announcement input and show toolbar
function expandAnnouncement() {
    const announceInput = document.getElementById("announceInput");
    const toolbar = document.getElementById("toolbar");
    announceInput.style.minHeight = "80px";
    toolbar.style.display = "flex";
}

// Hide toolbar and reset the input
function cancelAnnouncement() {
    const announceInput = document.getElementById("announceInput");
    const toolbar = document.getElementById("toolbar");
    announceInput.style.minHeight = "40px";
    announceInput.innerHTML = "";
    toolbar.style.display = "none";
}

    // Apply formatting commands to selected text
function formatText(command, button) {
    const announceInput = document.getElementById("announceInput");
    announceInput.focus();
    document.execCommand(command, false, null);
    // Toggle active state
    if (document.queryCommandState(command)) {
    button.classList.add("active");
    } else {
    button.classList.remove("active");
    }
}

// Post new announcement and save it to localStorage
function postAnnouncement() {
    const announceInput = document.getElementById("announceInput");
    const text = announceInput.innerHTML.trim();
    if (!text) {
    alert("Please write something before posting.");
    return;
    }
    announcements.push({
    text: text,
    date: new Date().toISOString(),
    teacherName: "Ankush Naskar"
    });
    localStorage.setItem("announcements", JSON.stringify(announcements));
    displayAnnouncements();
    cancelAnnouncement();
}

    // Display announcements
function displayAnnouncements() {
    const list = document.getElementById("announcementList");
    list.innerHTML = "";
    announcements.sort((a, b) => new Date(b.date) - new Date(a.date));

    announcements.forEach((ann, index) => {
    const card = document.createElement("div");
    card.classList.add("announcement-card");

    const dateString = new Date(ann.date).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "numeric"
    });

    card.innerHTML = `
        <div class="announcement-header">
        <img src="profile-pic.jpg" class="profile-pic" alt="Profile Picture" />
        <div class="announcement-info">
            <span class="teacher-name">${ann.teacherName}</span>
            <span class="announcement-date">${dateString}</span>
        </div>
        <div class="menu-container">
            <button class="menu-btn" onclick="toggleMenu(${index}, event)">⋮</button>
            <div class="menu-options" id="menu-${index}" style="display:none;">
            <button onclick="editAnnouncement(${index})">Edit</button>
            <button onclick="deleteAnnouncement(${index})">Delete</button>
            </div>
        </div>
        </div>
        <div class="announcement-body">
        <p id="announcement-text-${index}" class="announcement-text">${ann.text}</p>
        </div>
    `;
    list.appendChild(card);
    });
}

// Delete announcement
function deleteAnnouncement(index) {
    announcements.splice(index, 1);
    localStorage.setItem("announcements", JSON.stringify(announcements));
    displayAnnouncements();
}

// Edit announcement
function editAnnouncement(index) {
    const textElement = document.getElementById(`announcement-text-${index}`);
    const inputField = document.createElement("div");
    inputField.classList.add("edit-input");
    inputField.contentEditable = "true";
    inputField.innerHTML = announcements[index].text;

    const saveButton = document.createElement("button");
    saveButton.classList.add("save-btn");
    saveButton.textContent = "Save";
    saveButton.onclick = function () {
        saveAnnouncement(index, inputField);
    };

    const container = document.createElement("div");
    container.classList.add("edit-container");
    container.appendChild(inputField);
    container.appendChild(saveButton);

    textElement.parentNode.replaceChild(container, textElement);
    inputField.focus();
}

// Save announcement changes
function saveAnnouncement(index, inputField) {
    const newText = inputField.innerHTML.trim();
    if (!newText) {
        alert("Announcement cannot be empty!");
        return;
    }
    announcements[index].text = newText;
    localStorage.setItem("announcements", JSON.stringify(announcements));
    displayAnnouncements();
}

// Load announcements on page load
window.addEventListener("load", displayAnnouncements);
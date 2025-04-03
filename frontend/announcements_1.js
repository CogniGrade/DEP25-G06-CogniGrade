// ===== ANNOUNCEMENTS FEATURE =====
let announcements = [];

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

// Post new announcement and save it to the database via API
async function postAnnouncement() {
    const announceInput = document.getElementById("announceInput");
    const text = announceInput.innerHTML.trim();  // Use textContent for plain text
    console.log(text);
    if (!text) {
        alert("Please write something before posting.");
        return;
    }
    const classId = getQueryParam("class_id");
    if (!classId) {
        alert("Class ID not provided.");
        return;
    }
    try {
        const formData = new FormData();
        formData.append("content", text);
        const response = await fetch(`/classes/${classId}/announcements`, {
            method: "POST",
            body: formData
        });
        const data = await response.json();
        if (!response.ok) {
            alert(data.detail || "Error posting announcement");
            return;
        }
        // Re-fetch announcements after successful post
        await fetchAnnouncements();
        cancelAnnouncement();
    } catch (error) {
        console.error("Error posting announcement:", error);
        alert("Error posting announcement.");
    }
}


// Fetch announcements from the database via API and display them
async function fetchAnnouncements() {
    const classId = getQueryParam("class_id");
    if (!classId) {
        alert("Class ID not provided.");
        return;
    }
    try {
        const response = await fetch(`/classes/${classId}/announcements`);
        const data = await response.json();
        if (!data.success) {
            alert("Failed to load announcements.");
            return;
        }
        console.log(data.announcements);
        announcements = data.announcements;
        displayAnnouncements();
    } catch (error) {
        console.error("Error fetching announcements:", error);
        alert("Error fetching announcements.");
    }
}

// Display announcements
function displayAnnouncements() {
    const list = document.getElementById("announcementList");
    list.innerHTML = "";
    announcements.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    announcements.forEach((ann, index) => {
        const card = document.createElement("div");
        card.classList.add("announcement-card");
        const dateString = new Date(ann.created_at).toLocaleString("en-US", {
            month: "short",
            day: "numeric",
            year: "numeric",
            hour: "numeric",
            minute: "numeric"
        });

        
        //             CHANGE DATE TIMEZONE LATER

        card.innerHTML = `
            <div class="announcement-header">
                <img src="${ann.profile_pic}" class="profile-pic" alt="Profile Picture" />
                <div class="announcement-info">
                    <span class="teacher-name">${ann.author}</span>
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
                <p id="announcement-text-${index}" class="announcement-text">${ann.content}</p>
            </div>
        `;
        list.appendChild(card);
    });
}

// Toggle menu for edit/delete options
function toggleMenu(index, event) {
    event.stopPropagation();
    const menus = document.querySelectorAll(".menu-options");
    menus.forEach((menu, i) => {
      if (i === index) {
        menu.style.display = menu.style.display === "block" ? "none" : "block";
      } else {
        menu.style.display = "none";
      }
    });
  }

// Close any open menus when clicking outside
document.addEventListener("click", () => {
    const menus = document.querySelectorAll(".menu-options");
    menus.forEach(menu => (menu.style.display = "none"));
});


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
  

// Load announcements on page load
window.addEventListener("load", fetchAnnouncements);

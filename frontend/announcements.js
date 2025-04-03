// ===== ANNOUNCEMENTS FEATURE =====
let announcements = [];
let classId = null;

// Helper function to get query parameters
function getQueryParam(param) {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get(param);
}

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

// Post new announcement to API
async function postAnnouncement() {
    const announceInput = document.getElementById("announceInput");
    const text = announceInput.innerHTML.trim();
    if (!text) {
        alert("Please write something before posting.");
        return;
    }

    classId = getQueryParam("class_id");
    if (!classId) {
        alert("Class ID not provided");
        return;
    }

    try {
        const announcementData = {
            title: "New Announcement",
            content: text
        };

        const response = await authFetch(`/classes/${classId}/announcements`, {
            method: "POST",
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(announcementData)
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert(errorData.error || "Error creating announcement");
            return;
        }

        // Refresh announcements list
        fetchAnnouncements();
        cancelAnnouncement();
    } catch (error) {
        console.error("Error posting announcement:", error);
        alert("An error occurred while posting the announcement.");
    }
}

// Toggle announcement menu
function toggleMenu(index, event) {
    event.stopPropagation();
    const menuOptions = document.getElementById(`menu-${index}`);
    menuOptions.style.display = menuOptions.style.display === "none" ? "block" : "none";

    // Close other menus
    const menus = document.querySelectorAll('.menu-options');
    menus.forEach(menu => {
        if (menu.id !== `menu-${index}`) {
            menu.style.display = "none";
        }
    });

    // Close menu when clicking outside
    document.addEventListener('click', function closeMenu() {
        menuOptions.style.display = "none";
        document.removeEventListener('click', closeMenu);
    });
}

// Fetch announcements from API
async function fetchAnnouncements() {
    classId = getQueryParam("class_id");
    if (!classId) {
        console.error("Class ID not provided");
        return;
    }

    try {
        const response = await authFetch(`/classes/${classId}`, {
            headers: {
                "Content-Type": "application/json"
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            console.error("Error fetching announcements:", errorData);
            return;
        }

        const data = await response.json();
        announcements = data.announcements || [];
        displayAnnouncements();
    } catch (error) {
        console.error("Error fetching announcements:", error);
    }
}

// Display announcements from API data
function displayAnnouncements() {
    const list = document.getElementById("announcementList");
    if (!list) {
        console.error("Announcement list element not found");
        return;
    }

    list.innerHTML = "";

    if (announcements.length === 0) {
        list.innerHTML = "<p class='no-announcements'>No announcements yet</p>";
        return;
    }

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

        // Check if this announcement is related to an exam or assignment
        const isExam = ann.title && ann.title.includes("Exam");
        const isAssignment = ann.title && ann.title.includes("Assignment");
        const examClass = isExam ? "exam-announcement" : "";
        const assignmentClass = isAssignment ? "assignment-announcement" : "";

        // Set the appropriate onclick handler for exam/assignment announcements
        let clickHandler = "";
        let contentClass = "announcement-content";

        if (isExam && ann.exam_id) {
            clickHandler = `onclick="openExam(${ann.exam_id})"`;
            contentClass += " clickable";
        } else if (isAssignment && ann.assignment_id) {
            clickHandler = `onclick="openAssignment(${ann.assignment_id})"`;
            contentClass += " clickable";
        }

        // Use author_name from the API response
        const authorName = ann.author_name || "Unknown";

        // Use can_edit from the API response
        const canEdit = ann.can_edit || false;

        card.innerHTML = `
        <div class="announcement-header">
            <img src="profile-pic.jpg" class="profile-pic" alt="Profile Picture" />
            <div class="announcement-info">
                <span class="teacher-name">${authorName}</span>
                <span class="announcement-date">${dateString}</span>
            </div>
            <div class="menu-container">
                <button class="menu-btn" onclick="toggleMenu(${index}, event)">⋮</button>
                <div class="menu-options" id="menu-${index}" style="display:none;">
                    ${canEdit ? `<button onclick="editAnnouncement(${index})">Edit</button>` : ''}
                    ${canEdit ? `<button onclick="deleteAnnouncement(${index})">Delete</button>` : ''}
                </div>
            </div>
        </div>
        <div class="announcement-body">
            <div class="${contentClass} ${examClass} ${assignmentClass}" ${clickHandler}>
                ${ann.title ? `<h3 class="announcement-title">${ann.title}</h3>` : ''}
                <p id="announcement-text-${index}" class="announcement-text">${ann.content}</p>
            </div>
            
            <!-- Comments/Queries Section -->
            <div class="announcement-comments" id="comments-${ann.id}">
                <div class="comments-list" id="comments-list-${ann.id}">
                    <!-- Comments will be loaded here -->
                </div>
                <div class="add-comment">
                    <div class="comment-avatar">
                        <span>U</span>
                    </div>
                    <div class="comment-input-container">
                        <input type="text" class="comment-input" id="comment-input-${ann.id}" placeholder="Add class comment...">
                        <button class="post-comment-btn" onclick="postComment(${ann.id})">Post</button>
                    </div>
                </div>
            </div>
        </div>
        `;
        list.appendChild(card);

        // Load comments for this announcement
        loadComments(ann.id);
    });
}

// Handle clicking on exam announcements
function openExam(examId) {
    window.location.href = `exam.htm?exam_id=${examId}`;
}

// Handle clicking on assignment announcements
function openAssignment(assignmentId) {
    window.location.href = `assignment.htm?assignment_id=${assignmentId}`;
}

// Load comments for an announcement
async function loadComments(announcementId) {
    try {
        const response = await authFetch(`/classes/${classId}/announcements/${announcementId}/queries`, {
            headers: {
                "Content-Type": "application/json"
            }
        });

        if (!response.ok) {
            console.error("Error fetching comments");
            return;
        }

        const data = await response.json();
        displayComments(announcementId, data.queries || []);
    } catch (error) {
        console.error("Error loading comments:", error);
    }
}

// Display comments for an announcement
function displayComments(announcementId, comments) {
    const commentsList = document.getElementById(`comments-list-${announcementId}`);
    if (!commentsList) return;

    commentsList.innerHTML = "";
    if (comments.length === 0) return;

    comments.forEach(comment => {
        const commentEl = document.createElement("div");
        commentEl.classList.add("comment");

        const dateString = new Date(comment.created_at).toLocaleString("en-US", {
            month: "short",
            day: "numeric",
            hour: "numeric",
            minute: "numeric"
        });

        commentEl.innerHTML = `
            <div class="comment-header">
                <div class="comment-author">${comment.author_name}</div>
                <div class="comment-date">${dateString}</div>
            </div>
            <div class="comment-content">${comment.content}</div>
        `;
        commentsList.appendChild(commentEl);
    });
}

// Post a comment on an announcement
async function postComment(announcementId) {
    const commentInput = document.getElementById(`comment-input-${announcementId}`);
    const commentText = commentInput.value.trim();

    if (!commentText) return;

    try {
        const queryData = {
            title: "Comment",
            content: commentText,
            related_announcement_id: announcementId
        };

        const response = await authFetch(`/classes/${classId}/queries`, {
            method: "POST",
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(queryData)
        });

        if (!response.ok) {
            console.error("Error posting comment");
            return;
        }

        // Clear input and reload comments
        commentInput.value = "";
        loadComments(announcementId);
    } catch (error) {
        console.error("Error posting comment:", error);
    }
}

// Delete announcement
async function deleteAnnouncement(index) {
    const announcementId = announcements[index].id;
    
    // Confirm deletion
    if (!confirm("Are you sure you want to delete this announcement? All associated comments will also be deleted.")) {
        return;
    }

    try {
        const response = await authFetch(`/classes/${classId}/announcements/${announcementId}`, {
            method: "DELETE",
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert(errorData.error || "Error deleting announcement");
            return;
        }

        const data = await response.json();
        if (data.deleted_queries_count > 0) {
            alert(`Announcement deleted successfully. ${data.deleted_queries_count} comment${data.deleted_queries_count !== 1 ? 's' : ''} were also deleted.`);
        } else {
            alert("Announcement deleted successfully.");
        }

        // Refresh announcements list
        fetchAnnouncements();
    } catch (error) {
        console.error("Error deleting announcement:", error);
        alert("An error occurred while deleting the announcement.");
    }
}

// Edit announcement
function editAnnouncement(index) {
    const textElement = document.getElementById(`announcement-text-${index}`);
    const inputField = document.createElement("div");
    inputField.classList.add("edit-input");
    inputField.contentEditable = "true";
    inputField.innerHTML = announcements[index].content;

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
async function saveAnnouncement(index, inputField) {
    const newText = inputField.innerHTML.trim();
    if (!newText) {
        alert("Announcement cannot be empty!");
        return;
    }

    const announcementId = announcements[index].id;

    try {
        const announcementData = {
            title: announcements[index].title,
            content: newText
        };

        const response = await authFetch(`/classes/${classId}/announcements/${announcementId}`, {
            method: "PUT",
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(announcementData)
        });

        if (!response.ok) {
            const errorData = await response.json();
            alert(errorData.error || "Error updating announcement");
            return;
        }

        // Refresh announcements list
        fetchAnnouncements();
    } catch (error) {
        console.error("Error updating announcement:", error);
        alert("An error occurred while updating the announcement.");
    }
}

// Load announcements on page load
document.addEventListener("DOMContentLoaded", fetchAnnouncements);
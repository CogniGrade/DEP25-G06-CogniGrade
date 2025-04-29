function loadComponent(containerId, componentPath) {
    console.log(`Loading component into ${containerId} from ${componentPath}...`);
    fetch(componentPath)
        .then(response => response.text())
        .then(html => {
            document.getElementById(containerId).innerHTML = html;
            if (containerId === "topbar-container") {
                loadUserInfo();   
            }
        })
        .catch(error => console.error(`Error loading component ${componentPath}:`, error));
}

function loadUserInfo() {
    fetch("/get-info", { headers: { "Content-Type": "application/json" } })
        .then(response => response.json())
        .then(data => {
            if (data.user && data.user.full_name) {
                document.getElementById("userName").innerText = "Welcome, " + data.user.full_name;
            }
            
            // Add profile picture to topbar
            const userInfoElement = document.querySelector(".user-info");
            if (userInfoElement) {
                // Create profile picture element
                let profileImg = document.createElement("img");
                profileImg.id = "profilePic";
                profileImg.classList.add("profile-pic");
                profileImg.alt = "Profile";
                console.log(data.user.profile_picture);
                if (data.user && data.user.profile_picture) {
                    
                    let imagePath = "../" + data.user.profile_picture.replace("./", "");
                    profileImg.src = imagePath;
                } else {
                    // Fallback to avatar with initials if profile picture is not available
                    const initials = getInitials(data.user.full_name); // already exists in your code
                    profileImg.src = generateAvatar(initials);  
                    uploadGeneratedProfileImage(profileImg.src);           // now sends it to backend
                }
                
                // Add profile picture before the username text
                const rightDiv = document.querySelector(".right");
                if (rightDiv) {
                    rightDiv.insertBefore(profileImg, userInfoElement);
                }
                
                // Make profile picture clickable and link to settings
                profileImg.addEventListener("click", function() {
                    window.location.href = "settings.htm";
                });
                profileImg.style.cursor = "pointer";
            }
        })
        .catch(error => console.error("Error loading user info:", error));
}


// Load components
document.addEventListener("DOMContentLoaded", function() {
    loadComponent("topbar-container", "components/topbar.htm");
    loadComponent("sidebar-container", "components/sidebar.htm");
});

function base64ToBlob(base64Data, contentType = 'image/png') {
    const byteCharacters = atob(base64Data.split(',')[1]);
    const byteArrays = [];

    for (let offset = 0; offset < byteCharacters.length; offset += 512) {
        const slice = byteCharacters.slice(offset, offset + 512);

        const byteNumbers = new Array(slice.length);
        for (let i = 0; i < slice.length; i++) {
            byteNumbers[i] = slice.charCodeAt(i);
        }

        const byteArray = new Uint8Array(byteNumbers);
        byteArrays.push(byteArray);
    }

    return new Blob(byteArrays, { type: contentType });
}

function uploadGeneratedProfileImage(base64Image) {
    const imageBlob = base64ToBlob(base64Image, "image/png");
    const formData = new FormData();
    formData.append("profile_picture", imageBlob, "avatar.png");

    fetch("/update-profile", {
        method: "POST",
        body: formData
    })
    .then(response => response.json())
    .catch(error => {
        console.error("Error uploading profile image:", error);
    });
}


// Function to generate high-quality avatar if no profile picture exists
function generateAvatar(initials) {
    const canvas = document.createElement('canvas');
    // Use higher resolution for better quality
    canvas.width = 240;
    canvas.height = 240;
    const ctx = canvas.getContext('2d');
    
    // Create gradient background for better aesthetics
    // const gradient = ctx.createLinearGradient(0, 0, 240, 240);
    // gradient.addColorStop(0, '#4285f4');
    // gradient.addColorStop(1, '#34a853');
    ctx.fillStyle = '#624';// gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Set text style with larger, crisp font
    ctx.fillStyle = 'white';
    ctx.font = 'bold 110px Poppins, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    
    // Use shadow for better visibility
    ctx.shadowColor = 'rgba(0, 0, 0, 0.3)';
    ctx.shadowBlur = 4;
    ctx.shadowOffsetX = 0;
    ctx.shadowOffsetY = 2;
    
    // Draw initials on the canvas
    ctx.fillText(initials, canvas.width / 2, canvas.height / 2 + 10);
    
    return canvas.toDataURL('image/png', 1.0); // Use higher quality setting
  }

  // Function to get initials from full name
function getInitials(fullName) {
    if (!fullName) return "U";
    const nameParts = fullName.split(" ");
    return nameParts.length >= 2
      ? nameParts[0][0].toUpperCase() + nameParts[1][0].toUpperCase()
      : nameParts[0][0].toUpperCase();
}




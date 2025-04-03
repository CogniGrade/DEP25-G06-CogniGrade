function loadComponent(componentId, componentFile) {
    console.log("LOADING");
    fetch(componentFile)
        .then(response => response.text())
        .then(html => {
            document.getElementById(componentId).innerHTML = html;
        })
        .catch(error => console.error(`Error loading ${componentFile}:`, error));

    console.log("DONE");
}

// Load components
document.addEventListener("DOMContentLoaded", function() {
    loadComponent("topbar-container", "components/topbar.htm");
    loadComponent("sidebar-container", "components/sidebar.htm");
});

document.addEventListener('DOMContentLoaded', () => {
    const uploadAreas = document.querySelectorAll('.upload-area');

    uploadAreas.forEach(area => {
        area.addEventListener('dragover', event => {
            event.preventDefault();
            event.stopPropagation();
            area.classList.add('hover');
        });

        area.addEventListener('dragleave', event => {
            event.preventDefault();
            event.stopPropagation();
            area.classList.remove('hover');
        });

        area.addEventListener('drop', event => {
            event.preventDefault();
            event.stopPropagation();
            area.classList.remove('hover');
            const files = event.dataTransfer.files;
            if (files.length > 0) {
                const fileInput = area.querySelector('input[type="file"]');
                fileInput.files = files;
                handleFile(fileInput);
            }
        });

        area.addEventListener('click', () => {
            const fileInput = area.querySelector('input[type="file"]');
            fileInput.click();
        });
    });

    function handleFile(fileInput) {
        const file = fileInput.files[0];
        if (file) {
            console.log(`File uploaded: ${file.name}`);
            // Add your file processing logic here
        }
    }
});
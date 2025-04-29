  
  async function loadQuestions(examId) {
    try {
      const response = await fetch(`/exams/${examId}/questions/parts`);
      
      if (!response.ok) {
        throw new Error(`Failed to load questions (${response.status})`);
      }
      
      const data = await response.json();
      
      // Hide loading spinner
      document.getElementById('loading').style.display = 'none';
      
      // Show questions container
      const questionsContainer = document.getElementById('questions-container');
      questionsContainer.style.display = 'block';
      
      // Display exam info
      if (data.exam && data.exam.title) {
        document.getElementById('exam-info').textContent = `Exam: ${data.exam.title}`;
      } else {
        document.getElementById('exam-info').textContent = `Exam ID: ${examId}`;
      }
      
      if (!data || data.length === 0) {
        questionsContainer.innerHTML = '<p>No questions found for this exam.</p>';
        return;
      }
      
      // Render questions
      renderQuestions(data);
    } catch (error) {
      document.getElementById('loading').style.display = 'none';
      showAlert(`Error: ${error.message}`, 'danger');
      console.error('Error loading questions:', error);
    }
  }
  
function renderQuestions(questions) {
    const container = document.getElementById('questions-container');
    container.innerHTML = '';
    questions.forEach(question => {
        
        const questionCard = document.createElement('div');
        questionCard.className = 'question-card';
        questionCard.dataset.questionId = question.id;
        questionCard.dataset.questionNumber = question.question_number;  // Save question number

        // Create question header
        const header = document.createElement('div');
        header.className = 'question-header';

        // Title element (displays question number and part count)
        const title = document.createElement('div');
        title.className = 'question-title';
        title.textContent = `Question ${question.question_number} (${question.max_marks} marks)`;

        // Create a container for marks editing. (We add an editable input field.)
        const marksContainer = document.createElement('div');
        marksContainer.className = 'question-marks';
        // Add a label for clarity
        const marksLabel = document.createElement('label');
        marksLabel.textContent = 'Max Marks: ';
        // Create a number input field prefilled with question.max_marks
        const marksInput = document.createElement('input');
        marksInput.type = 'number';
        marksInput.value = question.max_marks;
        marksInput.className = 'marks-input';
        marksInput.style.width = '70px';
        marksInput.style.marginLeft = '8px';
        // Append label and input to the container
        marksContainer.appendChild(marksLabel);
        marksContainer.appendChild(marksInput);

        // Add main question "Add Subpart" button (for subparts of main question)
        const addSubpartBtn = document.createElement('button');
        addSubpartBtn.className = 'add-btn add-subpart-btn';
        addSubpartBtn.innerHTML = '<i class="fas fa-plus"></i> Add Subpart';
        addSubpartBtn.addEventListener('click', () => addSubpartToQuestion(question.id));

        // Assemble header: title, marks edit and button
        header.appendChild(title);
        header.appendChild(marksContainer);
        header.appendChild(addSubpartBtn);

        // Create question content (the prompt text)
        const content = document.createElement('div');
        content.className = 'question-content';
        content.textContent = question.text;

        // Create parts container (to display subpart labels)
        const partsContainer = document.createElement('div');
        partsContainer.className = 'parts-container';

        // Create parts section inside parts container
        const partsSection = document.createElement('div');
        partsSection.className = 'parts-section';
        partsSection.id = `parts-${question.id}`;
        partsContainer.appendChild(partsSection);

        if (question.part_labels) {
            
            let partLabels = [];
            try {
                partLabels = JSON.parse(question.part_labels);
                if (!Array.isArray(partLabels)) {
                    partLabels = [];
                }
            } catch (e) {
                console.warn(`Failed to parse part labels for question ${question.id}`, e);
            }
            renderPartLabels(partsSection, partLabels, question.id);
        } else {
            const noParts = document.createElement('p');
            noParts.className = 'no-parts';
            noParts.textContent = 'No parts defined for this question';
            partsSection.appendChild(noParts);
        }

        // Assemble the question card
        questionCard.appendChild(header);
        questionCard.appendChild(content);
        questionCard.appendChild(partsContainer);

        container.appendChild(questionCard);
    });
}

  
  function renderPartLabels(container, partLabels, questionId) {
    container.innerHTML = '';
    
    partLabels.forEach((label, index) => {
      const partItem = createPartItem(label, questionId, index, partLabels);
      container.appendChild(partItem);
    });
  }
  
function createPartItem(label, questionId, index, allLabels) {
    const partItem = document.createElement('div');
    partItem.className = 'part-item';
    partItem.dataset.partLabel = label;
    
    // Determine the level of indentation based on the number of dots
    const level = label.split('.').length - 1;
    partItem.classList.add(`level-${level}`);
    
    // Create label display
    const labelDisplay = document.createElement('span');
    labelDisplay.className = 'part-label';
    labelDisplay.textContent = label;
    
    // Create actions container
    const actionsDiv = document.createElement('div');
    actionsDiv.className = 'part-actions';
    
    // Add Subpart button for this part
    const addSubpartBtn = document.createElement('button');
    addSubpartBtn.className = 'add-btn';
    addSubpartBtn.innerHTML = '<i class="fas fa-plus"></i> Add Subpart';
    addSubpartBtn.addEventListener('click', () => addSubpart(questionId, label));
    
    // Check the number of direct children for this part
    const childCount = allLabels.filter(pl => {
        if (pl.startsWith(label + '.')) {
        const segments = pl.split('.');
        return segments.length === label.split('.').length + 1;
        }
        return false;
    }).length;
    if (childCount >= 6) {
        addSubpartBtn.disabled = true;
        addSubpartBtn.style.opacity = 0.5;
        addSubpartBtn.style.cursor = 'not-allowed';
    } else {
        addSubpartBtn.disabled = false;
        addSubpartBtn.style.opacity = 1;
        addSubpartBtn.style.cursor = 'pointer';
    }
    
    // Remove button for this part
    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-btn';
    removeBtn.innerHTML = '<i class="fas fa-times"></i> Remove';
    removeBtn.addEventListener('click', () => removePart(questionId, label));
    
    actionsDiv.appendChild(addSubpartBtn);
    actionsDiv.appendChild(removeBtn);
    
    partItem.appendChild(labelDisplay);
    partItem.appendChild(actionsDiv);
    
    return partItem;
}

  
function addSubpartToQuestion(questionId) {
    const partsSection = document.getElementById(`parts-${questionId}`);
    let partLabels = getPartLabels(questionId);
    
    // Get the main question number from the question card's data attribute
    const questionCard = document.querySelector(`[data-question-id="${questionId}"]`);
    const parentQuestionNumber = questionCard.dataset.questionNumber;

    // Find existing main-level parts: those starting with "{questionNumber}."
    const mainParts = partLabels.filter(label => label.startsWith(`${parentQuestionNumber}.`));
    
    // If already six main parts, disable the header button and alert the user.
    const headerAddBtn = questionCard.querySelector('.add-subpart-btn');
    if (mainParts.length >= 6) {
        headerAddBtn.disabled = true;
        headerAddBtn.style.opacity = 0.5;
        headerAddBtn.style.cursor = 'not-allowed';
        showAlert("Maximum of 6 subparts reached for this question", "danger");
        return;
    }
    
    let newLabel;
    if (mainParts.length === 0) {
        newLabel = `${parentQuestionNumber}.1`;
    } else {
        // Get the current highest number after the dot and increment it
        const highest = Math.max(...mainParts.map(l => {
        const parts = l.split('.');
        return parseInt(parts[1], 10) || 0;
        }));
        newLabel = `${parentQuestionNumber}.${highest + 1}`;
    }
    
    partLabels.push(newLabel);
    partLabels = sortPartLabels(partLabels);
    
    // Remove 'no parts' message if it exists
    const noPartsMsg = partsSection.querySelector('.no-parts');
    if (noPartsMsg) {
        noPartsMsg.remove();
    }
    
    renderPartLabels(partsSection, partLabels, questionId);
}


function addSubpart(questionId, parentLabel) {
    // Calculate the parent's depth (number of segments separated by ".")
    const parentDepth = parentLabel.split('.').length;
    
    // Disallow any further sublevel if maximum depth is reached
    if (parentDepth >= 6) {
        showAlert("No more sublevels are allowed", "danger");
        return;
    }
    
    // Also check if the current parent already has six direct children
    let partLabels = getPartLabels(questionId);
    const directChildren = partLabels.filter(label => {
        if (label.startsWith(parentLabel + '.')) {
        return label.split('.').length === parentDepth + 1;
        }
        return false;
    });
    if (directChildren.length >= 6) {
        // Disable should be applied by the UI update in renderPartLabels, but also alert here.
        showAlert("Maximum of 6 subparts reached for this part", "danger");
        return;
    }
    
    const partsSection = document.getElementById(`parts-${questionId}`);
    
    // Find the highest subpart number for this parent label
    let highestSubpart = 0;
    const parentWithDot = parentLabel + '.';
    
    partLabels.forEach(label => {
        if (label === parentLabel) return; // Skip the parent itself
        
        // Check if this is a direct child of the parent (its depth is parent's depth + 1)
        if (label.startsWith(parentWithDot)) {
        const parts = label.split('.');
        if (parts.length === parentDepth + 1) {
            const lastPart = parseInt(parts[parts.length - 1], 10);
            if (lastPart > highestSubpart) highestSubpart = lastPart;
        }
        }
    });
    
    // Create new subpart label
    const newLabel = `${parentLabel}.${highestSubpart + 1}`;
    partLabels.push(newLabel);
    partLabels = sortPartLabels(partLabels);
    
    renderPartLabels(partsSection, partLabels, questionId);
}


  
function removePart(questionId, labelToRemove) {
    if (!confirm("Do you really want to delete this Part?")) return;
    
    let partLabels = getPartLabels(questionId);
    
    // Remove the selected label and its entire sub-tree
    partLabels = partLabels.filter(pl => !(pl === labelToRemove || pl.startsWith(labelToRemove + '.')));
    
    // Determine the parent label for the part being deleted
    const lastDot = labelToRemove.lastIndexOf('.');
    const parent = lastDot > 0 ? labelToRemove.substring(0, lastDot) : null;  
    if (parent) {
        // Extract direct children under the same parent from the remaining labels.
        const parentDepth = parent.split('.').length;
        let siblings = partLabels.filter(pl => {
        if (!pl.startsWith(parent + '.')) return false;
        return pl.split('.').length === parentDepth + 1;
        });
        // Sort siblings by their last numeric segment
        siblings.sort((a, b) => {
        const aNum = parseInt(a.split('.').pop(), 10);
        const bNum = parseInt(b.split('.').pop(), 10);
        return aNum - bNum;
        });
        
        // Determine the numeric value of the removed part
        const removedNum = parseInt(labelToRemove.split('.').pop(), 10);
        
        // For each sibling with a number greater than the removed part,
        // update the label by subtracting 1 from their last number.
        siblings.forEach(sib => {
        const sibParts = sib.split('.');
        const sibNumber = parseInt(sibParts.pop(), 10);
        if (sibNumber > removedNum) {
            const oldPrefix = parent + '.' + sibNumber;
            const newPrefix = parent + '.' + (sibNumber - 1);
            // Update all labels that begin with the old prefix
            partLabels = partLabels.map(pl => {
            if (pl === oldPrefix || pl.startsWith(oldPrefix + '.')) {
                return newPrefix + pl.substring(oldPrefix.length);
            }
            return pl;
            });
        }
        });
    }
    
    // Re-render the parts section with the updated part labels
    const partsSection = document.getElementById(`parts-${questionId}`);
    if (partLabels.length === 0) {
        partsSection.innerHTML = '';
        const noParts = document.createElement('p');
        noParts.className = 'no-parts';
        noParts.textContent = 'No parts defined for this question';
        partsSection.appendChild(noParts);
    } else {
        renderPartLabels(partsSection, partLabels, questionId);
    }
}

  
function getPartLabels(questionId) {
    const partsSection = document.getElementById(`parts-${questionId}`);
    const partItems = partsSection.querySelectorAll('.part-item');
    
    if (partItems.length === 0) {
      return [];
    }
    
    // Extract labels from DOM
    return Array.from(partItems).map(item => item.dataset.partLabel);
}
  
function sortPartLabels(labels) {
    return labels.sort((a, b) => {
      const aParts = a.split('.').map(Number);
      const bParts = b.split('.').map(Number);
      
      // Compare each part numerically
      for (let i = 0; i < Math.max(aParts.length, bParts.length); i++) {
        // If a part doesn't exist, consider it less than any number
        const aVal = i < aParts.length ? aParts[i] : -1;
        const bVal = i < bParts.length ? bParts[i] : -1;
        
        if (aVal !== bVal) {
          return aVal - bVal;
        }
      }
      
      // If all parts are the same up to the shortest array length,
      // the shorter array comes first
      return aParts.length - bParts.length;
    });
}
  
async function saveAllChanges(examId) {
    const questionCards = document.querySelectorAll('.question-card');
    const updates = [];

    questionCards.forEach(card => {
        const questionId = card.dataset.questionId;
        const partLabels = getPartLabels(questionId);
        // Retrieve updated max marks from the marks input field within this card
        const marksInput = card.querySelector('.marks-input');
        let maxMarks = null;
        if (marksInput) {
            maxMarks = parseInt(marksInput.value, 10);
        }

        updates.push({
            questionId,
            partLabels,
            maxMarks
        });
    });

    try {
        // Show loading state
        const saveBtn = document.getElementById('save-all-btn');
        const originalBtnText = saveBtn.innerHTML;
        saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
        saveBtn.disabled = true;

        // Send updates to backend
        const response = await fetch(`/exams/${examId}/questions/parts`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ updates })
        });

        if (!response.ok) {
        throw new Error(`Failed to save changes (${response.status})`);
        }

        showAlert('All changes saved successfully!', 'success');
        saveBtn.innerHTML = originalBtnText;
        saveBtn.disabled = false;
    } catch (error) {
        showAlert(`Error: ${error.message}`, 'danger');
        console.error('Error saving changes:', error);
        const saveBtn = document.getElementById('save-all-btn');
        saveBtn.innerHTML = '<i class="fas fa-save"></i> Save All Changes';
        saveBtn.disabled = false;
    }
}


function showAlert(message, type) {
    const alertsContainer = document.getElementById('alerts-container');
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.textContent = message;
    
    // Clear existing alerts
    alertsContainer.innerHTML = '';
    
    // Add new alert
    alertsContainer.appendChild(alert);
    
    // Auto-dismiss after 5 seconds
    setTimeout(() => {
      alert.remove();
    }, 5000);
}

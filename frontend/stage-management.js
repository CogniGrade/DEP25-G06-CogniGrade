let currentStage = 0;
let doc_stage = 0;

function getDocStage(current_stage) {
    if (current_stage <= 2) {
        return 0;
    } else if (current_stage === 3) {
        return 1;
    } else if (current_stage === 4) {
        return 2;
    } else if (current_stage >= 5 && current_stage <= 8) {
        return 3;
    } else {
        return -1; // or some default/error value if stage is unknown
    }
}


async function fetchExamStage() {
    const examId = getQueryParam('exam_id');

    try {
        const response = await fetch(`/exams/${examId}/stage`);
        if (!response.ok) {
            throw new Error("Failed to fetch exam stage");
        }
        const data = await response.json();
        console.log("Current Exam Stage:", data.exam_stage);
        currentStage = data.exam_stage;
    
    } catch (error) {
        console.error("Error fetching exam stage:", error);
    }
}

async function postExamStage(stage) {
    const examId = getQueryParam('exam_id');
    try {
    const response = await fetch(`/exams/${examId}/stage`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exam_stage: stage })
    });
    if (!response.ok) {
        throw new Error("Failed to update exam stage");
    }
    console.log("Exam stage updated successfully:", stage);
    } catch (error) {
    console.error("Error updating exam stage:", error);
    }

    if (stage === 7){
        gradeExam(examId);
    }
}

function updateExamResult() {
    const examId = getQueryParam("exam_id");
    fetch(`/exam/${examId}/add-result`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    })
    .then(response => response.json())
    .then(data => {
      console.log("Exam result updated:", data);
      // Optionally refresh any UI component showing overall exam statistics.
    })
    .catch(err => console.error("Error updating exam result:", err));
  }


async function gradeExam(examId) {
    try {
      const resp = await fetch(`/${examId}/grade-exam`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      if (!resp.ok) {
        const err = await resp.json();
        console.error('Error:', err.detail || resp.status);
        return;
      }
      const data = await resp.json();
      console.log('Grades for exam', data.exam_id, 'student', data.student_id);
      data.results.forEach(r => {
        console.log(`Q${r.question_number}: ${r.grade} — ${r.reasoning}`);
      });

      updateExamResult();
    } catch (e) {
      console.error('Network error:', e);
    }
}
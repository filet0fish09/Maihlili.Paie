document.addEventListener('DOMContentLoaded', function() {
    var calendarEl = document.getElementById('calendar');
    
    var calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        locale: 'fr',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,timeGridDay'
        },
        businessHours: {
            daysOfWeek: [1, 2, 3, 4, 5], // Lundi à Vendredi
            startTime: '08:00',
            endTime: '18:00',
        },
        
        // Charger les événements depuis l'API
        events: function(fetchInfo, successCallback, failureCallback) {
            fetch(`/api/events?start=${fetchInfo.startStr}&end=${fetchInfo.endStr}`)
                .then(response => response.json())
                .then(data => successCallback(data))
                .catch(error => {
                    console.error('Erreur lors du chargement des événements:', error);
                    failureCallback(error);
                });
        },
        
        // Permettre la sélection de créneaux
        selectable: true,
        selectMirror: true,
        
        // Événement lors de la sélection d'un créneau
        select: function(info) {
            // Créer un modal ou un formulaire pour ajouter un assignment
            createAssignmentModal(info.start, info.end);
        },
        
        // Événement lors du clic sur un événement existant
        eventClick: function(info) {
            if (confirm('Voulez-vous supprimer cet assignment ?')) {
                deleteAssignment(info.event.id);
            }
        },
        
        // Permettre le drag & drop
        editable: true,
        
        // Événement lors du déplacement d'un événement
        eventDrop: function(info) {
            updateAssignment(info.event.id, info.event.start, info.event.end);
        },
        
        // Événement lors du redimensionnement
        eventResize: function(info) {
            updateAssignment(info.event.id, info.event.start, info.event.end);
        }
    });
    
    calendar.render();
});

// Fonction pour créer un assignment
function createAssignmentModal(start, end) {
    // Simple prompt pour l'instant - vous pouvez améliorer avec un vrai modal
    const employeeId = prompt('ID de l\'employé:');
    const shiftId = prompt('ID du shift:');
    
    if (employeeId && shiftId) {
        fetch('/api/assignments', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                employee_id: parseInt(employeeId),
                shift_id: parseInt(shiftId),
                start: start.toISOString(),
                end: end.toISOString()
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                location.reload(); // Recharger pour voir le nouvel assignment
            } else {
                alert('Erreur: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Erreur:', error);
            alert('Erreur lors de la création de l\'assignment');
        });
    }
}

// Fonction pour supprimer un assignment
function deleteAssignment(assignmentId) {
    fetch(`/api/assignments/${assignmentId}`, {
        method: 'DELETE',
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Erreur: ' + data.error);
        }
    })
    .catch(error => {
        console.error('Erreur:', error);
        alert('Erreur lors de la suppression');
    });
}

// Fonction pour mettre à jour un assignment
function updateAssignment(assignmentId, start, end) {
    fetch(`/api/assignments/${assignmentId}`, {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            start: start.toISOString(),
            end: end.toISOString()
        })
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            alert('Erreur: ' + data.error);
            location.reload(); // Revert changes
        }
    })
    .catch(error => {
        console.error('Erreur:', error);
        location.reload();
    });
}
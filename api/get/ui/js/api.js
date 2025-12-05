function api(endpoint, method, data) {
    fetch('/api/' + method + '/' + endpoint, { // '/api/server/create'
        method: method, // 'POST'
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            'data': data
        })
    })
    .then(response => {
                if (!response.ok) {
                    return response.json().then(err => { throw new Error(err.error || `HTTP error! status: ${response.status}`) });
                }
                return response.json();
            })
    .then(data => {
        console.log('Data sent successfully:', data);
    })
    .catch((error) => {
        console.error('Error sending data:', error);
    });
}
async function authFetch(url, options = {}) {
    const response = await fetch(url, options);
    if (response.status === 401) {
      // Redirect to login or show error message
      window.location.href = "login.htm?error=Not%20Authorized";
      throw new Error("Not Authorized");
    }
    return response;
  }
  
window.addEventListener("pageshow", function(event) {
    if (event.persisted) {
        window.location.reload();
    }
});

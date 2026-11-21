async function responseDetail(response, fallback) {
    try {
        const result = await response.json();
        return result.detail || result.message || fallback;
    } catch (error) {
        return fallback;
    }
}

async function logout() {
    let csrfToken = sessionStorage.getItem("csrf_token") || "";

    try {
        const csrfResponse = await fetch("/auth/csrf-token", {
            credentials: "include"
        });

        if (csrfResponse.ok) {
            const result = await csrfResponse.json();
            if (!result.csrf_token) {
                throw new Error("The server did not provide a CSRF token.");
            }
            csrfToken = result.csrf_token;
            sessionStorage.setItem("csrf_token", csrfToken);
        } else if (csrfResponse.status === 401) {
            csrfToken = "";
        } else {
            throw new Error(
                await responseDetail(csrfResponse, "Unable to refresh the security token.")
            );
        }

        const headers = {};
        if (csrfToken) {
            headers["X-CSRF-Token"] = csrfToken;
        }

        const response = await fetch("/auth/logout", {
            method: "POST",
            credentials: "include",
            headers
        });

        if (!response.ok) {
            throw new Error(
                await responseDetail(response, "Logout failed. Please try again.")
            );
        }

        sessionStorage.removeItem("csrf_token");
        window.location.href = "/pages/login.html";
    } catch (error) {
        console.error("Logout error:", error);
        alert(error.message || "Unable to connect to the server.");
    }
}

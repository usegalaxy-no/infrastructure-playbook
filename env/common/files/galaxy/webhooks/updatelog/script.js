function removeUpdateLogOverlay() {
    document.getElementById("updatelog-container").style.visibility = "hidden";
}

function showUpdateLogOverlay() {
    document.getElementById("updatelog-container").style.visibility = "visible";
}

function addUpdateLogIframe() {
    const updateLogPage = `/static/updatelog.html?v=`+Math.floor(Math.random() * 1000000); // add random argument to prevent caching

    document.querySelector("body.full-content").insertAdjacentHTML(
        "afterbegin",
        `
            <div id="updatelog-container" style="visibility: hidden">
                <div id="updatelog-screen-overlay"></div>
                <div id="updatelog-screen">
                    <div id="updatelog-header">
                        <iframe id="updatelog-embed" src="${updateLogPage}" width="80%" height="80%"></iframe>
                    </div>
                </div>
            </div>`
    );

    // Clicking outside of the overlay closes it
    document.getElementById("updatelog-screen").addEventListener("click", () => {
        removeUpdateLogOverlay();
    });
}

/* The masthead icon may not exist yet when this webhook executes; we need this to wait for that to happen.
 * elementReady function from gist:
 * https://gist.github.com/jwilson8767/db379026efcbd932f64382db4b02853e
 */
function elementReadyUpdateLog(selector) {
    return new Promise((resolve, reject) => {
        const el = document.querySelector(selector);
        if (el) {
            resolve(el);
        }
        new MutationObserver((mutationRecords, observer) => {
            // Query for elements matching the specified selector
            Array.from(document.querySelectorAll(selector)).forEach((element) => {
                resolve(element);
                //Once we have resolved we don't need the observer anymore.
                observer.disconnect();
            });
        }).observe(document.documentElement, {
            childList: true,
            subtree: true,
        });
    });
}

elementReadyUpdateLog("#updatelog a").then((el) => {
    // External stuff may also have attached a click handler here (vue-based masthead)
    // replace with a clean copy of the node to remove all that cruft.
    clean = el.cloneNode(true);
    el.parentNode.replaceChild(clean, el);

    // This gets added by default.
    addUpdateLogIframe();

    clean.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        showUpdateLogOverlay();
    });
});

// Remove the overlay on escape button click
document.addEventListener("keydown", (e) => {
    // Check for escape button - "27"
    if (e.which === 27 || e.keyCode === 27) {
        removeUpdateLogOverlay();
    }
});

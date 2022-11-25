function removeMonitorOverlay() {
    document.getElementById("monitor-container").style.visibility = "hidden";
}

function showMonitorOverlay() {
    document.getElementById("monitor-container").style.visibility = "visible";
}

function addMonitorIframe() {
    const monitorPage = `/static/slurm_cluster_stats.html`;

    document.querySelector("body.full-content").insertAdjacentHTML(
        "afterbegin",
        `
            <div id="monitor-container" style="visibility: hidden">
                <div id="monitor-screen-overlay"></div>
                <div id="monitor-screen">
                    <div id="monitor-header">
                        <iframe id="monitor-embed" src="${monitorPage}" width="80%" height="80%"></iframe>
                    </div>
                </div>
            </div>`
    );

    // Clicking outside of the overlay closes it
    document.getElementById("monitor-screen").addEventListener("click", () => {
        removeMonitorOverlay();
    });
}

/* The masthead icon may not exist yet when this webhook executes; we need this to wait for that to happen.
 * elementReady function from gist:
 * https://gist.github.com/jwilson8767/db379026efcbd932f64382db4b02853e
 */
function elementReadyMonitor(selector) {
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

elementReadyMonitor("#monitor a").then((el) => {
    // External stuff may also have attached a click handler here (vue-based masthead)
    // replace with a clean copy of the node to remove all that cruft.
    clean = el.cloneNode(true);
    el.parentNode.replaceChild(clean, el);

    // This gets added by default.
    addMonitorIframe();

    clean.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        showMonitorOverlay();
    });
});

// Remove the overlay on escape button click
document.addEventListener("keydown", (e) => {
    // Check for escape button - "27"
    if (e.which === 27 || e.keyCode === 27) {
        removeMonitorOverlay();
    }
});

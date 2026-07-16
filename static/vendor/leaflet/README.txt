Leaflet (the map library) is stored here so the app makes no external requests
for it at runtime — important on locked-down networks.

leaflet.js and leaflet.css are downloaded and SHA-256-verified automatically the
first time you run the app on a machine with internet (or run:  python vendor_leaflet.py).
Once these files are present, the app serves the map library entirely locally.

To distribute to an offline machine, include this folder with the files in it.
Leaflet 1.9.4, BSD-2-Clause license — https://leafletjs.com/

CHOPPY WAVES & CAPILLARY RIPPLES

A static research gallery for the choppy-wave + Cho experiments on Unity.

Gallery: https://npizzo.github.io/choppy-cho-gallery/
Repository: https://github.com/npizzo/choppy-cho-gallery

The gallery compares two-way parent/current coupling with prescribed parent
evolution. It presents surface movies, underwater mean-flow structures, mean
square slope and parent-wave sidebands. The Cho viscosity is 2.4 times the
molecular value. Cho responds to the parent and current; it does not yet feed
back into either. This is a reduced wave/mean-flow model, not a simulation of
a moving air-water interface.

Only real imported outputs are displayed. The initial snapshot records that
validation job 66079691 was submitted; its result is not yet synchronized.
An absent movie is not evidence that the simulation failed.

Preview locally from this repository:
  python3 -m http.server 8000 --directory gallery
Then open http://localhost:8000.

Validate public content:
  python3 scripts/check_gallery.py gallery

Publication and Unity setup instructions: docs/unity.txt
The publisher is a separate sidecar; it does not change the validated
simulation source or attach secrets to scientific outputs. Publish only
gallery/ through GitHub Pages, using the included GitHub Actions workflow.
Raw simulation fields and access credentials must stay out of this repository.

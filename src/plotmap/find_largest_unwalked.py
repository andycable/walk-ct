import numpy as np
import pandas as pd
from scipy import ndimage
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# Load data
print("Loading data...")
df = pd.read_csv("Distance_3_ct.csv", low_memory=False)
df = df.dropna(subset=['lat', 'long', 'Dist'])
df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
df = df.dropna()
print(f"Loaded {len(df)} points")

# Grid spacing is 0.001 degrees (precision level 3)
GRID = 0.001

# Convert lat/long to grid indices
lat_min, lat_max = df['lat'].min(), df['lat'].max()
lon_min, lon_max = df['long'].min(), df['long'].max()

print(f"Lat range: {lat_min} to {lat_max}")
print(f"Lon range: {lon_min} to {lon_max}")

rows = int(round((lat_max - lat_min) / GRID)) + 1
cols = int(round((lon_max - lon_min) / GRID)) + 1
print(f"Grid size: {rows} x {cols}")

# Create grids: one for distance values, one for presence (inside CT)
dist_grid = np.full((rows, cols), np.nan)
present_grid = np.zeros((rows, cols), dtype=bool)

row_idx = np.round((df['lat'].values - lat_min) / GRID).astype(int)
col_idx = np.round((df['long'].values - lon_min) / GRID).astype(int)
dist_grid[row_idx, col_idx] = df['Dist'].values
present_grid[row_idx, col_idx] = True

print(f"Points in grid: {present_grid.sum()}")

# Define "unwalked" as Dist >= 0.5 (far from any walked path)
UNWALKED_THRESHOLD = 0.5
unwalked = present_grid & (dist_grid >= UNWALKED_THRESHOLD)
walked = present_grid & (dist_grid < UNWALKED_THRESHOLD)

print(f"Unwalked cells: {unwalked.sum()}")
print(f"Walked cells: {walked.sum()}")

# Find connected components of unwalked areas
labeled, num_features = ndimage.label(unwalked)
print(f"Found {num_features} unwalked regions")

# Identify CT border cells: present cells that have a non-present neighbor
# (i.e., cells at the edge of the data = edge of Connecticut)
border_mask = np.zeros_like(present_grid)
for dr, dc in [(-1,0),(1,0),(0,-1),(0,1)]:
    shifted = np.roll(np.roll(present_grid.astype(int), dr, axis=0), dc, axis=1)
    # Cells that are present but have a non-present neighbor
    border_mask |= (present_grid & (shifted == 0))

# Also mark actual grid edges as border
border_mask[0, :] = present_grid[0, :]
border_mask[-1, :] = present_grid[-1, :]
border_mask[:, 0] = present_grid[:, 0]
border_mask[:, -1] = present_grid[:, -1]

print(f"Border cells: {border_mask.sum()}")

# Find which components touch the border
border_labels = set(np.unique(labeled[border_mask]))
border_labels.discard(0)  # 0 is background
print(f"Regions touching border: {len(border_labels)}")

# Compute perimeter for each non-border component
# Perimeter = number of edge cells (cells with at least one non-same-label neighbor)
results = []
for label_id in range(1, num_features + 1):
    if label_id in border_labels:
        continue

    component = (labeled == label_id)
    area = component.sum()

    if area < 5:  # skip tiny clusters
        continue

    # Compute perimeter: count cells on the edge of the component
    eroded = ndimage.binary_erosion(component)
    perimeter = (component & ~eroded).sum()

    # Get bounding box for reporting
    ys, xs = np.where(component)
    lat_center = lat_min + ys.mean() * GRID
    lon_center = lon_min + xs.mean() * GRID

    results.append({
        'label': label_id,
        'area': area,
        'perimeter': perimeter,
        'lat_center': lat_center,
        'lon_center': lon_center,
        'lat_min': lat_min + ys.min() * GRID,
        'lat_max': lat_min + ys.max() * GRID,
        'lon_min': lon_min + xs.min() * GRID,
        'lon_max': lon_min + xs.max() * GRID,
    })

results.sort(key=lambda x: x['perimeter'], reverse=True)

print(f"\nInterior unwalked regions (not touching CT border): {len(results)}")
print("\nTop 10 by perimeter:")
for i, r in enumerate(results[:10]):
    print(f"  {i+1}. Label {r['label']}: perimeter={r['perimeter']}, area={r['area']}, "
          f"center=({r['lat_center']:.4f}, {r['lon_center']:.4f})")

# Get the largest by perimeter
largest = results[0]
largest_mask = (labeled == largest['label'])

print(f"\nLargest interior unwalked area:")
print(f"  Perimeter: {largest['perimeter']} cells")
print(f"  Area: {largest['area']} cells")
print(f"  Center: ({largest['lat_center']:.4f}, {largest['lon_center']:.4f})")
print(f"  Bounds: lat [{largest['lat_min']:.4f}, {largest['lat_max']:.4f}], "
      f"lon [{largest['lon_min']:.4f}, {largest['lon_max']:.4f}]")

# Create visualization
print("\nGenerating PNG...")

fig, ax = plt.subplots(1, 1, figsize=(15, 12))

# Build color image
# Start with black background
img = np.zeros((rows, cols, 3), dtype=np.uint8)

# Color scheme matching Rivers.png color2
# under 0.0 / under 0.2: pink/salmon
salmon = np.array([248, 118, 109])
olive = np.array([183, 159, 0])
green = np.array([0, 186, 56])
blue = np.array([97, 156, 255])

# Apply colors based on Dist values
mask_02 = present_grid & (dist_grid < 0.33)
mask_04 = present_grid & (dist_grid >= 0.33) & (dist_grid < 0.66)
mask_06 = present_grid & (dist_grid >= 0.66) & (dist_grid < 0.99)
mask_boundary = present_grid & (dist_grid >= 0.99)

img[mask_02] = salmon
img[mask_04] = olive
img[mask_06] = green
img[mask_boundary] = blue

# Highlight the largest unwalked area in bright yellow
img[largest_mask] = [255, 255, 0]

# Also highlight top 5 in different colors for context
highlight_colors = [
    [255, 255, 0],   # yellow - #1
    [255, 140, 0],   # orange - #2
    [255, 0, 255],   # magenta - #3
    [0, 255, 255],   # cyan - #4
    [255, 80, 80],   # red - #5
]

for i, r in enumerate(results[:5]):
    mask = (labeled == r['label'])
    img[mask] = highlight_colors[i]

# Flip vertically so north is up (lat increases upward)
img = img[::-1]

# Set extent for proper lat/long axes
extent = [lon_min, lon_max, lat_min, lat_max]
ax.imshow(img, extent=extent, aspect=1.4)

# Add legend
legend_items = [
    mpatches.Patch(color=np.array(highlight_colors[0])/255, label=f'#1 Largest (perim={results[0]["perimeter"]}, area={results[0]["area"]})'),
    mpatches.Patch(color=np.array(highlight_colors[1])/255, label=f'#2 (perim={results[1]["perimeter"]}, area={results[1]["area"]})'),
    mpatches.Patch(color=np.array(highlight_colors[2])/255, label=f'#3 (perim={results[2]["perimeter"]}, area={results[2]["area"]})'),
    mpatches.Patch(color=np.array(highlight_colors[3])/255, label=f'#4 (perim={results[3]["perimeter"]}, area={results[3]["area"]})'),
    mpatches.Patch(color=np.array(highlight_colors[4])/255, label=f'#5 (perim={results[4]["perimeter"]}, area={results[4]["area"]})'),
    mpatches.Patch(color=salmon/255, label='Walked (close)'),
    mpatches.Patch(color=olive/255, label='Medium distance'),
    mpatches.Patch(color=green/255, label='Far from walked'),
    mpatches.Patch(color=blue/255, label='Boundary'),
]
ax.legend(handles=legend_items, loc='lower right', fontsize=8, framealpha=0.9)

ax.set_xlabel('Longitude')
ax.set_ylabel('Latitude')
ax.set_title('Andy Walks Connecticut - Top 5 Largest Interior Unwalked Areas by Perimeter', fontsize=14)

plt.tight_layout()
plt.savefig('Largest_Unwalked.png', dpi=150, bbox_inches='tight', facecolor='black')
print("Saved Largest_Unwalked.png")

# Also create a zoomed view of the largest area
fig2, ax2 = plt.subplots(1, 1, figsize=(12, 10))

pad = 0.02  # padding in degrees
zoom_extent = [
    largest['lon_min'] - pad,
    largest['lon_max'] + pad,
    largest['lat_min'] - pad,
    largest['lat_max'] + pad,
]

ax2.imshow(img, extent=extent, aspect=1.4)
ax2.set_xlim(zoom_extent[0], zoom_extent[1])
ax2.set_ylim(zoom_extent[2], zoom_extent[3])
ax2.set_xlabel('Longitude')
ax2.set_ylabel('Latitude')
ax2.set_title(f'Largest Interior Unwalked Area (Zoomed)\n'
              f'Center: ({largest["lat_center"]:.4f}, {largest["lon_center"]:.4f}), '
              f'Perimeter: {largest["perimeter"]} cells, Area: {largest["area"]} cells',
              fontsize=12)
plt.tight_layout()
plt.savefig('Largest_Unwalked_Zoom.png', dpi=150, bbox_inches='tight', facecolor='black')
print("Saved Largest_Unwalked_Zoom.png")

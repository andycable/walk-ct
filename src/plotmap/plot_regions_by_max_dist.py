import numpy as np
import pandas as pd
from scipy import ndimage
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import ListedColormap, BoundaryNorm

# Load data
print("Loading data...")
df = pd.read_csv("Distance_3_ct.csv", low_memory=False)
df = df.dropna(subset=['lat', 'long', 'Dist'])
df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
df['Dist'] = pd.to_numeric(df['Dist'], errors='coerce')
df = df.dropna()
print(f"Loaded {len(df)} points")

# Grid spacing is 0.001 degrees (precision level 3)
GRID = 0.001

lat_min, lat_max = df['lat'].min(), df['lat'].max()
lon_min, lon_max = df['long'].min(), df['long'].max()

rows = int(round((lat_max - lat_min) / GRID)) + 1
cols = int(round((lon_max - lon_min) / GRID)) + 1
print(f"Grid size: {rows} x {cols}")

# Create grids
dist_grid = np.full((rows, cols), np.nan)
present_grid = np.zeros((rows, cols), dtype=bool)

row_idx = np.round((df['lat'].values - lat_min) / GRID).astype(int)
col_idx = np.round((df['long'].values - lon_min) / GRID).astype(int)
dist_grid[row_idx, col_idx] = df['Dist'].values
present_grid[row_idx, col_idx] = True

print(f"Points in grid: {present_grid.sum()}")

# Define unwalked threshold (same as find_largest_unwalked.py)
UNWALKED_THRESHOLD = 0.5
unwalked = present_grid & (dist_grid >= UNWALKED_THRESHOLD)
walked = present_grid & (dist_grid < UNWALKED_THRESHOLD)

print(f"Unwalked cells: {unwalked.sum()}")
print(f"Walked cells: {walked.sum()}")

# Find connected components of unwalked areas
labeled, num_features = ndimage.label(unwalked)
print(f"Found {num_features} unwalked regions")

# For each region, compute max distance
region_max_dist = np.zeros(num_features + 1)  # index 0 = background
for label_id in range(1, num_features + 1):
    mask = (labeled == label_id)
    region_max_dist[label_id] = np.nanmax(dist_grid[mask])

# Create a grid where each cell gets its region's max distance
# Walked cells get value 0 (will be colored separately)
max_dist_grid = np.full((rows, cols), np.nan)

# Assign walked cells a small value to distinguish from background
max_dist_grid[walked] = 0.0

# Assign each unwalked cell the max distance of its region
for r in range(rows):
    for c in range(cols):
        if labeled[r, c] > 0:
            max_dist_grid[r, c] = region_max_dist[labeled[r, c]]

# Vectorized version (much faster than the loop above - replace the loop)
# Actually let's do it properly with vectorized approach
print("Assigning region max distances...")
max_dist_grid_v = np.full((rows, cols), np.nan)
max_dist_grid_v[walked] = 0.0
# Use the lookup array to map labels to max distances
label_to_max = region_max_dist[labeled]  # broadcasts: labeled has shape (rows,cols)
unwalked_mask = labeled > 0
max_dist_grid_v[unwalked_mask] = label_to_max[unwalked_mask]

# Count regions by bin
bins = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
for i in range(len(bins) - 1):
    count = np.sum((region_max_dist[1:] >= bins[i]) & (region_max_dist[1:] < bins[i+1]))
    print(f"  Regions with max dist {bins[i]:.2f} - {bins[i+1]:.2f}: {count}")
count = np.sum(region_max_dist[1:] >= bins[-1])
print(f"  Regions with max dist >= {bins[-1]:.2f}: {count}")

# Build the image
print("Generating image...")
fig, ax = plt.subplots(1, 1, figsize=(15, 12))

# Color bins: walked (< 0.5), then 0.25-mile intervals for regions
# We'll map the max_dist_grid_v values to colors
# Background = black (NaN), walked = dark green, regions by distance
boundaries = [0, 0.5, 1.0, 1.5, 2.0, 2.5, 100]
colors = [
    '#1a9850',  # walked (0 to 0.5): green
    '#4575b4',  # 0.50 - 1.00: blue
    '#74add1',  # 1.00 - 1.50: light blue
    '#fee090',  # 1.50 - 2.00: yellow
    '#f46d43',  # 2.00 - 2.50: red-orange
    '#67001f',  # 2.50+: dark red
]

cmap = ListedColormap(colors)
norm = BoundaryNorm(boundaries, cmap.N)

# Flip so north is up
img_data = max_dist_grid_v[::-1]

extent = [lon_min, lon_max, lat_min, lat_max]
ax.imshow(img_data, extent=extent, aspect=1.4, cmap=cmap, norm=norm,
          interpolation='nearest')

# Set black background for NaN (outside CT)
ax.set_facecolor('black')
fig.patch.set_facecolor('black')

# Legend
legend_items = [
    mpatches.Patch(color='#1a9850', label='Walked (< 0.50 mi)'),
    mpatches.Patch(color='#4575b4', label='0.50 - 1.00 mi'),
    mpatches.Patch(color='#74add1', label='1.00 - 1.50 mi'),
    mpatches.Patch(color='#fee090', label='1.50 - 2.00 mi'),
    mpatches.Patch(color='#f46d43', label='2.00 - 2.50 mi'),
    mpatches.Patch(color='#67001f', label='2.50+ mi'),
]
ax.legend(handles=legend_items, loc='lower right', fontsize=9,
          framealpha=0.9, title='Max Distance in Region')

ax.set_xlabel('Longitude', color='white')
ax.set_ylabel('Latitude', color='white')
ax.set_title('Andy Walks Connecticut - Unwalked Regions by Max Distance',
             fontsize=14, color='white')
ax.tick_params(colors='white')

plt.tight_layout()
plt.savefig('Region_Max_Distance.png', dpi=150, bbox_inches='tight',
            facecolor='black')
print("Saved Region_Max_Distance.png")

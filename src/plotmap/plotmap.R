# install.packages("ggplot2")
# install.packages("maps")
# install.packages("ggmap")
# install.packages("dplyr")
# install.packages("sp")

library(ggplot2)
library(ggmap)
library(dplyr)
library(sf)
library(tigris)

options(tigris_use_cache = TRUE)

# Fetch all boundaries from US Census TIGER/Line for consistency
ct_state <- states(cb = TRUE) %>% filter(STUSPS == "CT")
ct_counties <- counties(state = "CT", cb = TRUE)
ct_towns <- county_subdivisions(state = "CT", cb = TRUE)


# Connecticut bounding box for clipping
ct_xlim <- c(-73.73, -71.77)
ct_ylim <- c(41.00, 42.06)

# --- Classify shared town borders as walked/unwalked per edge ---
# Compute shared boundary geometries once and cache as RDS
boundary_geoms_file <- "town_boundary_geoms.rds"
if (file.exists(boundary_geoms_file)) {
  boundary_geoms <- readRDS(boundary_geoms_file)
} else {
  ct_towns_ll <- st_transform(ct_towns, 4326)
  sf_use_s2(FALSE)  # s2 returns empty for polygon-polygon intersection
  adj <- st_touches(ct_towns_ll, sparse = TRUE)
  boundary_geoms <- list()
  for (i in seq_len(nrow(ct_towns_ll))) {
    for (j in adj[[i]]) {
      if (j <= i) next
      t1 <- ct_towns_ll$NAME[i]; t2 <- ct_towns_ll$NAME[j]
      if (t1 > t2) { tmp <- t1; t1 <- t2; t2 <- tmp }
      shared <- tryCatch(
        st_intersection(st_geometry(ct_towns_ll)[i], st_geometry(ct_towns_ll)[j]),
        error = function(e) NULL)
      if (is.null(shared) || length(shared) == 0 || all(st_is_empty(shared))) next
      lines <- tryCatch(st_collection_extract(shared, "LINESTRING"), error = function(e) shared)
      if (length(lines) == 0 || all(st_is_empty(lines)) || !any(grepl("LINE", st_geometry_type(lines)))) next
      boundary_geoms[[paste(t1, t2, sep = "|")]] <- lines
    }
  }
  saveRDS(boundary_geoms, boundary_geoms_file)
  sf_use_s2(TRUE)
}

# Load walked coordinates and filter to CT bounding box
walked_pts <- read.csv("../all.3.uniq.csv")
walked_pts$lat <- as.numeric(walked_pts$lat)
walked_pts <- walked_pts %>%
  filter(!is.na(lat), lat >= ct_ylim[1], lat <= ct_ylim[2],
         long >= ct_xlim[1], long <= ct_xlim[2])

# Town polygons in WGS84 for point-in-polygon checks
ct_towns_ll <- st_transform(ct_towns, 4326)

# Load existing boundary CSV and add crossed column if missing
bounds <- read.csv("town_boundaries.csv")
if (!"crossed" %in% names(bounds)) bounds$crossed <- FALSE

# Only check boundaries not yet marked as crossed
# A boundary is "crossed" if walked points exist in BOTH towns near the shared border
pad <- 0.005  # ~500m padding around boundary bbox
for (r in which(!bounds$crossed)) {
  key <- paste(bounds$Town1[r], bounds$Town2[r], sep = "|")
  geom <- boundary_geoms[[key]]
  if (is.null(geom)) next

  # Filter walked points within the boundary's expanded bounding box
  bb <- st_bbox(geom)
  nearby <- walked_pts %>%
    filter(lat >= bb["ymin"] - pad, lat <= bb["ymax"] + pad,
           long >= bb["xmin"] - pad, long <= bb["xmax"] + pad)
  if (nrow(nearby) == 0) next

  # Check if walked points exist in both towns
  nearby_sf <- st_as_sf(nearby, coords = c("long", "lat"), crs = 4326)
  town1_poly <- ct_towns_ll[ct_towns_ll$NAME == bounds$Town1[r], ]
  town2_poly <- ct_towns_ll[ct_towns_ll$NAME == bounds$Town2[r], ]
  in_town1 <- any(st_intersects(nearby_sf, town1_poly, sparse = FALSE))
  in_town2 <- any(st_intersects(nearby_sf, town2_poly, sparse = FALSE))
  bounds$crossed[r] <- in_town1 && in_town2
}

# Save updated CSV
write.csv(bounds, "town_boundaries.csv", row.names = FALSE)
cat("Boundaries crossed:", sum(bounds$crossed), "of", nrow(bounds), "\n")

# Build walked/unwalked border geometry lists for plotting
walked_edge_list <- list()
unwalked_edge_list <- list()
for (r in seq_len(nrow(bounds))) {
  key <- paste(bounds$Town1[r], bounds$Town2[r], sep = "|")
  geom <- boundary_geoms[[key]]
  if (is.null(geom)) next
  if (bounds$crossed[r]) walked_edge_list[[length(walked_edge_list) + 1]] <- geom
  else unwalked_edge_list[[length(unwalked_edge_list) + 1]] <- geom
}

walked_borders <- st_sfc(do.call(c, walked_edge_list), crs = 4326)
if (length(unwalked_edge_list) > 0) {
  unwalked_borders <- st_sfc(do.call(c, unwalked_edge_list), crs = 4326)
} else {
  unwalked_borders <- st_sfc(crs = 4326)
}

# Town name labels at centroids
town_labels <- ct_towns_ll
town_labels$geometry <- st_point_on_surface(st_geometry(town_labels))

file_path <- "Distance_3.csv"
delta = 0.0005


my_data <- read.csv(file_path)  %>% select(long, lat, Dist) %>% filter(Dist < 3.5)
my_data$colorx <- ifelse(my_data$Dist < 0.0, "under 0.0"
                , ifelse(my_data$Dist < 0.91, "under 1.0"
                , ifelse(my_data$Dist < 1.01, "zboundary"
                , ifelse(my_data$Dist < 1.41, "under 1.5"
                , ifelse(my_data$Dist < 1.51, "zboundary"
                , ifelse(my_data$Dist < 1.91, "under 2.0"
                , ifelse(my_data$Dist < 1.92, "under 2.0"
                , "under 1.0")))))))
my_data$color2 <- ifelse(my_data$Dist < 0.0, "under 0.0"
                , ifelse(my_data$Dist < 0.33, "under 0.2"
                , ifelse(my_data$Dist < 0.66, "under 0.4"
                , ifelse(my_data$Dist < 0.99, "under 0.6"
                , ifelse(my_data$Dist < 1.11, "zboundary"
                , ifelse(my_data$Dist < 1.21, "zboundary"
                , ifelse(my_data$Dist < 1.31, "zboundary"
                , "zboundary")))))))

# Mark the largest contiguous unwalked area (western border strip in NW CT)
my_data$color2_highlight <- my_data$color2
largest_unwalked <- my_data$Dist > 1.0 &
  my_data$long >= -73.5535 & my_data$long <= -73.4875 &
  my_data$lat >= 41.7005 & my_data$lat <= 42.0505
my_data$color2_highlight[largest_unwalked] <- "largest_unwalked"

# Filter points to those inside CT using the TIGER state boundary
my_points <- st_as_sf(my_data, coords = c("long", "lat"), crs = 4326)
ct_state_4326 <- st_transform(ct_state, crs = 4326)
is_inside <- st_within(my_points, st_union(ct_state_4326), sparse = FALSE)[, 1]
my_ct_data <- my_data[is_inside, ]

my_plot <- ggplot() +
  geom_sf(data = ct_state, fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = colorx)) +
  geom_sf(data = st_sf(geometry = unwalked_borders), color = "gray20", linewidth = 0.3) +
  geom_sf(data = st_sf(geometry = walked_borders), color = "gray80", linewidth = 0.3) +
  geom_sf_text(data = town_labels, aes(label = NAME), size = 1.5, family = "sans", fontface = "plain", color = "black") +
  scale_size_continuous(range = c(3, 5)) + # Adjust the size range as needed
  coord_sf(xlim = ct_xlim, ylim = ct_ylim) +
  theme_minimal() +
  theme(panel.background = element_rect(fill = "white", color = NA),
        plot.background = element_rect(fill = "white", color = NA)) +
  labs(title = "Andy Walks Connecticut")

my_plot2 <- ggplot() +
  geom_sf(data = ct_state, fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = color2)) +
  geom_sf(data = st_sf(geometry = unwalked_borders), color = "gray20", linewidth = 0.3) +
  geom_sf(data = st_sf(geometry = walked_borders), color = "gray80", linewidth = 0.3) +
  geom_sf_text(data = town_labels, aes(label = NAME), size = 1.5, family = "sans", fontface = "plain", color = "black") +
  scale_size_continuous(range = c(3, 5)) + # Adjust the size range as needed
  coord_sf(xlim = ct_xlim, ylim = ct_ylim) +
  theme_minimal() +
  theme(panel.background = element_rect(fill = "white", color = NA),
        plot.background = element_rect(fill = "white", color = NA)) +
  labs(title = "Andy Walks Connecticut")

# Save the ggplot as a PNG file
ggsave("AndyWalksConnecticut.png", my_plot, width = 15, height = 15)
ggsave("Rivers.png", my_plot2, width = 15, height = 15)

# NW zoom with largest unwalked area highlighted in yellow
my_plot_nw <- ggplot() +
  geom_sf(data = ct_state, fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = color2_highlight)) +
  geom_sf(data = st_sf(geometry = unwalked_borders), color = "gray20", linewidth = 0.3) +
  geom_sf(data = st_sf(geometry = walked_borders), color = "gray80", linewidth = 0.3) +
  geom_sf_text(data = town_labels, aes(label = NAME), size = 1.5, family = "sans", fontface = "plain", color = "black") +
  scale_fill_manual(values = c("under 0.0" = "#F8766D", "under 0.2" = "#F8766D", "under 0.4" = "#B79F00", "under 0.6" = "#00BA38", "zboundary" = "#619CFF", "largest_unwalked" = "yellow")) +
  coord_sf(xlim = c(-73.73, -73.2), ylim = c(41.7, 42.05)) +
  theme_minimal() +
  theme(panel.background = element_rect(fill = "white", color = NA),
        plot.background = element_rect(fill = "white", color = NA)) +
  labs(title = "NW Connecticut - Largest Unwalked Area Highlighted")
ggsave("Rivers_NW_zoom_highlight.png", my_plot_nw, width = 15, height = 15)

# Distance heatmap: color each cell by 0.25-mile distance bins
my_ct_data$dist_bin <- cut(my_ct_data$Dist,
  breaks = c(0, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, Inf),
  labels = c("0 - 0.25", "0.25 - 0.50", "0.50 - 0.75", "0.75 - 1.00",
             "1.00 - 1.25", "1.25 - 1.50", "1.50 - 1.75", "1.75 - 2.00",
             "2.00 - 2.25", "2.25 - 2.50", "2.50+"),
  right = FALSE, include.lowest = TRUE)

dist_colors <- c(
  "0 - 0.25"    = "#313695",
  "0.25 - 0.50" = "#4575b4",
  "0.50 - 0.75" = "#74add1",
  "0.75 - 1.00" = "#abd9e9",
  "1.00 - 1.25" = "#e0f3f8",
  "1.25 - 1.50" = "#fee090",
  "1.50 - 1.75" = "#fdae61",
  "1.75 - 2.00" = "#f46d43",
  "2.00 - 2.25" = "#d73027",
  "2.25 - 2.50" = "#a50026",
  "2.50+"        = "#67001f"
)

my_plot_dist <- ggplot() +
  geom_sf(data = ct_state, fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = dist_bin)) +
  geom_sf(data = st_sf(geometry = unwalked_borders), color = "gray20", linewidth = 0.3) +
  geom_sf(data = st_sf(geometry = walked_borders), color = "gray80", linewidth = 0.3) +
  geom_sf_text(data = town_labels, aes(label = NAME), size = 1.5, family = "sans", fontface = "plain", color = "black") +
  scale_fill_manual(values = dist_colors, name = "Distance (miles)", drop = FALSE) +
  coord_sf(xlim = ct_xlim, ylim = ct_ylim) +
  theme_minimal() +
  theme(panel.background = element_rect(fill = "white", color = NA),
        plot.background = element_rect(fill = "white", color = NA)) +
  labs(title = "Andy Walks Connecticut - Distance from Nearest Walk")
ggsave("Distance_Heatmap.png", my_plot_dist, width = 15, height = 15)


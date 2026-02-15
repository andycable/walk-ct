library(ggplot2)
library(maps)
library(dplyr)
library(sp)
library(osmdata)

# Get Connecticut map data
ct_map <- map_data("state", region = "connecticut")
ct_counties <- map_data("county", region = "connecticut")
ct_boundary <- getbb("Connecticut") %>% opq() %>% add_osm_feature(key = "boundary", value = "administrative")

file_path <- "Distance_3_ct.csv"
delta <- 0.0005

my_data <- read.csv(file_path) %>% select(long, lat, Dist) %>% filter(Dist < 3.5)

# Filter to points inside CT
is_inside <- (point.in.polygon(my_data$long, my_data$lat, ct_map$long, ct_map$lat) != 0)
my_ct_data <- filter(my_data, is_inside)

# Create 0.25-mile distance bins
my_ct_data$dist_bin <- cut(my_ct_data$Dist,
  breaks = c(0, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, Inf),
  labels = c("0 - 0.25", "0.25 - 0.50", "0.50 - 0.75", "0.75 - 1.00",
             "1.00 - 1.25", "1.25 - 1.50", "1.50 - 1.75", "1.75 - 2.00",
             "2.00 - 2.25", "2.25 - 2.50", "2.50+"),
  right = FALSE, include.lowest = TRUE)

# Blue (close) -> Yellow -> Red (far) color ramp
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
  geom_polygon(data = ct_map, aes(x = long, y = lat, group = group), fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = dist_bin)) +
  geom_polygon(data = ct_counties, aes(x = long, y = lat, group = group), fill=NA, color = "black") +
  geom_sf(data = ct_boundary$osm_lines, inherit.aes = TRUE, fill=NA, color = "black", size = 0.1) +
  scale_fill_manual(values = dist_colors, name = "Distance (miles)", drop = FALSE) +
  coord_fixed(ratio = 1.4) +
  theme_minimal() +
  labs(title = "Andy Walks Connecticut - Distance from Nearest Walk")

ggsave("Distance_Heatmap.png", my_plot_dist, width = 15, height = 15)
cat("Saved Distance_Heatmap.png\n")

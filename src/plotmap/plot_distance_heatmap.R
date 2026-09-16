library(ggplot2)
library(maps)
library(dplyr)
library(sp)

# NO osmdata HERE, DELIBERATELY. There used to be:
#
#   library(osmdata)
#   ct_boundary <- getbb("Connecticut") %>% opq() %>%
#                    add_osm_feature(key = "boundary", value = "administrative")
#   ... + geom_sf(data = ct_boundary$osm_lines, ...)
#
# and it drew nothing. add_osm_feature() only BUILDS an Overpass query; running
# it takes osmdata_sf(), which this script never called. So ct_boundary was an
# overpass_query object - bbox, prefix, suffix, features, osm_types - with no
# osm_lines in it, and that geom_sf layer was handed NULL every time. Rendering
# with and against the layer, in this exact order, gives byte-identical PNGs.
#
# The order mattered and still does: geom_sf quietly adds coord_sf, so had it
# sat AFTER coord_fixed() below it would have replaced the 1.4 aspect ratio.
# It sat before, so coord_fixed won and the layer changed nothing at all.
#
# Dead as it was, it still broke the script outright, because getbb() goes to
# the network through httr2: httr2 1.2.2 calls curl::curl_modify_url and needs
# curl >= 6.4.0, while the newest curl BINARY for R 4.3.3 is 6.2.2. Every run
# died on "'curl_modify_url' is not an exported object from 'namespace:curl'"
# before drawing a pixel. Removing a layer that drew nothing also removes the
# only reason this script needed the network.

# Get Connecticut map data
ct_map <- map_data("state", region = "connecticut")
ct_counties <- map_data("county", region = "connecticut")

file_path <- "Distance_3_ct.csv"
delta <- 0.0005

my_data <- read.csv(file_path) %>% select(long, lat, Dist) %>% filter(Dist < 3.5)

# Filter to points inside CT
is_inside <- (point.in.polygon(my_data$long, my_data$lat, ct_map$long, ct_map$lat) != 0)
my_ct_data <- filter(my_data, is_inside)

# Create 0.25-mile distance bins.
#
# These stop at 1.50+ because the data does: once ct_outline started dropping
# the offshore islands the maximum fell from 2.38 mi - Chimon Island, off
# Norwalk, which no walker can reach - to 1.67 on the mainland. The old breaks
# ran to "2.50+", and with drop = FALSE below that left four empty entries in
# the legend and a red that nothing on the map was ever painted, so the whole
# ramp read cooler than the coverage actually is.
my_ct_data$dist_bin <- cut(my_ct_data$Dist,
  breaks = c(0, 0.25, 0.50, 0.75, 1.00, 1.25, 1.50, Inf),
  labels = c("0 - 0.25", "0.25 - 0.50", "0.50 - 0.75", "0.75 - 1.00",
             "1.00 - 1.25", "1.25 - 1.50", "1.50+"),
  right = FALSE, include.lowest = TRUE)

# Blue (close) -> Yellow -> Red (far) color ramp
dist_colors <- c(
  "0 - 0.25"    = "#313695",
  "0.25 - 0.50" = "#4575b4",
  "0.50 - 0.75" = "#abd9e9",
  "0.75 - 1.00" = "#e0f3f8",
  "1.00 - 1.25" = "#fee090",
  "1.25 - 1.50" = "#f46d43",
  "1.50+"       = "#a50026"
)

my_plot_dist <- ggplot() +
  geom_polygon(data = ct_map, aes(x = long, y = lat, group = group), fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = dist_bin)) +
  geom_polygon(data = ct_counties, aes(x = long, y = lat, group = group), fill=NA, color = "black") +
  scale_fill_manual(values = dist_colors, name = "Distance (miles)", drop = FALSE) +
  coord_fixed(ratio = 1.4) +
  theme_minimal() +
  labs(title = "Andy Walks Connecticut - Distance from Nearest Walk")

# bg = "white" is not decoration. theme_minimal() leaves plot.background blank,
# and ggsave then takes its fill from the theme and writes a TRANSPARENT PNG -
# 67% of this one, background and margins alike. Anything that shows it on a
# dark surface turns the state black and the axis text and title with it. The
# committed file used to be opaque RGB; this keeps it that way.
ggsave("Distance_Heatmap.png", my_plot_dist, width = 15, height = 15, bg = "white")
cat("Saved Distance_Heatmap.png\n")

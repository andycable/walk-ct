# install.packages("ggplot2")
# install.packages("maps")
# install.packages("ggmap")
# install.packages("dplyr")
# install.packages("sp")

library(ggplot2)
library(maps)
library(ggmap)
library(dplyr)
library(sp)
library(osmdata)


# Get Connecticut map data
ct_map <- map_data("state", region = "connecticut")
ct_counties <- map_data("county", region = "connecticut")

# Fetch town borders (admin_level=8 in OSM = towns/cities in CT)
ct_towns <- getbb("Connecticut") %>%
  opq(timeout = 120) %>%
  add_osm_feature(key = "boundary", value = "administrative") %>%
  add_osm_feature(key = "admin_level", value = "8") %>%
  osmdata_sf()


# Connecticut bounding box for clipping
ct_xlim <- c(-73.73, -71.77)
ct_ylim <- c(41.00, 42.06)

file_path <- "Distance_3_ct.csv"
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

ct_boundary_coordinates <- ct_map %>% select(long, lat)

ct_polygon <- SpatialPolygons(list(Polygons(list(Polygon(ct_boundary_coordinates)), ID = "CT")))

is_inside <- (point.in.polygon(my_data$long, my_data$lat, ct_map$long, ct_map$lat) != 0)

my_ct_data <- filter(my_data, is_inside)

my_plot <- ggplot() +
  geom_polygon(data = ct_map, aes(x = long, y = lat, group = group), fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = colorx)) +
  geom_polygon(data = ct_counties, aes(x = long, y = lat, group = group), fill=NA, color = "black") +
  geom_sf(data = ct_towns$osm_multipolygons, inherit.aes = TRUE, fill = NA, color = "gray40", size = 0.2) +
  scale_size_continuous(range = c(3, 5)) + # Adjust the size range as needed
  coord_sf(xlim = ct_xlim, ylim = ct_ylim) +
  theme_minimal() +
  theme(panel.background = element_rect(fill = "white", color = NA),
        plot.background = element_rect(fill = "white", color = NA)) +
  labs(title = "Andy Walks Connecticut")

my_plot2 <- ggplot() +
  geom_polygon(data = ct_map, aes(x = long, y = lat, group = group), fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = color2)) +
  geom_polygon(data = ct_counties, aes(x = long, y = lat, group = group), fill=NA, color = "black") +
  geom_sf(data = ct_towns$osm_multipolygons, inherit.aes = TRUE, fill = NA, color = "gray40", size = 0.2) +
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
  geom_polygon(data = ct_map, aes(x = long, y = lat, group = group), fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = color2_highlight)) +
  geom_polygon(data = ct_counties, aes(x = long, y = lat, group = group), fill=NA, color = "black") +
  geom_sf(data = ct_towns$osm_multipolygons, inherit.aes = TRUE, fill = NA, color = "gray40", size = 0.2) +
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
  geom_polygon(data = ct_map, aes(x = long, y = lat, group = group), fill = "white", color = "black") +
  geom_rect(data = my_ct_data, aes(xmin = long-delta, xmax = long+delta, ymin = lat-delta, ymax = lat+delta, fill = dist_bin)) +
  geom_polygon(data = ct_counties, aes(x = long, y = lat, group = group), fill=NA, color = "black") +
  geom_sf(data = ct_towns$osm_multipolygons, inherit.aes = TRUE, fill = NA, color = "gray40", size = 0.2) +
  scale_fill_manual(values = dist_colors, name = "Distance (miles)", drop = FALSE) +
  coord_sf(xlim = ct_xlim, ylim = ct_ylim) +
  theme_minimal() +
  theme(panel.background = element_rect(fill = "white", color = NA),
        plot.background = element_rect(fill = "white", color = NA)) +
  labs(title = "Andy Walks Connecticut - Distance from Nearest Walk")
ggsave("Distance_Heatmap.png", my_plot_dist, width = 15, height = 15)


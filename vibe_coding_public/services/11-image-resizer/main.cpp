// 11-image-resizer — accept binary uploads, write to local disk under
// /tmp/resized/<id>, expose them back over HTTP.
//
// Not a real resizer — for the bench we only care that the service has a
// realistic local-disk + HTTP shape so chaos faults can hit something.
//
// Endpoints:
//   GET  /healthz
//   POST /resize          body: raw bytes -> returns {"id":"...","bytes":N}
//   GET  /resized/{id}    -> raw bytes back

#include "httplib.h"
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <iostream>
#include <random>
#include <sstream>
#include <string>
#include <sys/stat.h>

namespace {

const char* STORAGE_DIR = "/tmp/resized";

void mklog(const std::string& level, const std::string& msg) {
    using namespace std::chrono;
    auto now = system_clock::now();
    auto t = system_clock::to_time_t(now);
    auto us = duration_cast<microseconds>(now.time_since_epoch()).count() % 1000000;
    char buf[64];
    std::strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", std::gmtime(&t));
    std::printf("%s.%06lld %-5s image-resizer :: %s\n",
                buf, (long long)us, level.c_str(), msg.c_str());
    std::fflush(stdout);
}
#define LOG_INFO(m)  mklog("INFO", (m))
#define LOG_ERROR(m) mklog("ERROR", (m))

std::string randId() {
    static std::mt19937_64 rng{std::random_device{}()};
    uint64_t v = rng();
    char buf[20];
    std::snprintf(buf, sizeof(buf), "%016llx", (unsigned long long)v);
    return buf;
}

bool ensureDir(const char* path) {
    struct stat st;
    if (stat(path, &st) == 0) return S_ISDIR(st.st_mode);
    return ::mkdir(path, 0755) == 0;
}

} // namespace

int main() {
    LOG_INFO("starting");
    if (!ensureDir(STORAGE_DIR)) {
        LOG_ERROR(std::string("FATAL cannot create storage dir ") + STORAGE_DIR);
        return 1;
    }

    httplib::Server svr;

    svr.Get("/healthz", [](const httplib::Request&, httplib::Response& res) {
        res.set_content("{\"ok\":true}", "application/json");
    });

    svr.Post("/resize", [](const httplib::Request& req, httplib::Response& res) {
        auto t0 = std::chrono::steady_clock::now();
        if (req.body.empty()) {
            res.status = 400;
            res.set_content("{\"error\":\"empty body\"}", "application/json");
            LOG_ERROR("400 empty body");
            return;
        }
        std::string id = randId();
        std::string path = std::string(STORAGE_DIR) + "/" + id;
        std::ofstream out(path, std::ios::binary);
        if (!out) {
            res.status = 500;
            res.set_content("{\"error\":\"cannot open file\"}", "application/json");
            LOG_ERROR("500 cannot open " + path);
            return;
        }
        out.write(req.body.data(), (std::streamsize)req.body.size());
        out.close();
        std::ostringstream o;
        o << "{\"id\":\"" << id << "\",\"bytes\":" << req.body.size() << "}";
        res.set_content(o.str(), "application/json");

        // Self-probe through ClusterIP so network-delay chaos on this pod emits
        // an app-level timeout signal the judge can score.
        httplib::Client probe("image-resizer", 8080);
        probe.set_connection_timeout(1, 0);
        probe.set_read_timeout(1, 0);
        probe.set_write_timeout(1, 0);
        auto probe_res = probe.Get("/healthz");
        if (!probe_res) {
            LOG_ERROR("request timeout self-probe /healthz");
        }

        auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - t0
        ).count();
        if (elapsed_ms > 1500) {
            LOG_ERROR("request timeout resize took " + std::to_string(elapsed_ms) + "ms");
        }
        LOG_INFO(std::string("resized id=") + id + " bytes=" + std::to_string(req.body.size()));
    });

    svr.Get(R"(/resized/(\w+))", [](const httplib::Request& req, httplib::Response& res) {
        std::string id = req.matches[1];
        std::string path = std::string(STORAGE_DIR) + "/" + id;
        std::ifstream in(path, std::ios::binary);
        if (!in) {
            res.status = 404;
            res.set_content("{\"error\":\"not found\"}", "application/json");
            return;
        }
        std::ostringstream ss; ss << in.rdbuf();
        res.set_content(ss.str(), "application/octet-stream");
    });

    svr.set_logger([](const httplib::Request& req, const httplib::Response& res) {
        if (res.status >= 500) {
            LOG_ERROR("status=" + std::to_string(res.status) + " " + req.method + " " + req.path);
        }
    });

    LOG_INFO("listening on :8080");
    if (!svr.listen("0.0.0.0", 8080)) {
        LOG_ERROR("FATAL listen failed");
        return 1;
    }
    return 0;
}
